# Nice IT4WIFI — NHK / T4 / DMP protocol notes

Reverse‑engineered reference for the IT4WIFI Wi‑Fi interface, gathered while adapting the
upstream integration. Written down so the next person (or the next debugging session)
doesn't start from zero. Sources: live probing of an IT4WIFI (fw 0.4.43) + decompiled
*MyNice* / *MyNice Pro* Android apps.

> ⚠️ This is documentation of an undocumented protocol. Values are what was observed on
> one interface + a Nice ROBUS `SG01a`. Treat firmware‑specific details as "seen here",
> not "guaranteed everywhere".

---

## 1. Transport

- TLS on **TCP 443**. The interface has a **1024‑bit DH key** and a stack **without
  RFC 5746**. A modern client must set `OP_LEGACY_SERVER_CONNECT` and
  `set_ciphers("DEFAULT:@SECLEVEL=0")`, then it negotiates `TLSv1.2 /
  DHE-RSA-AES256-SHA256`.
- Messages are framed **STX (0x02) … ETX (0x03)** around an XML `<Request>` / `<Response>`.
- Request envelope:
  ```xml
  <Request id="…" source="…" target="<MAC>" gw="gwID"
           protocolType="NHK" protocolVersion="1.0" type="…"> … </Request>
  ```
  `id = (sequence << 8) | (session_id & 0xFF)`.

## 2. Modes and discovery

The interface runs **HomeKit** *or* **MyNice** technology, never both — and they differ at
the port level:

| Mode | mDNS | ports |
|---|---|---|
| HomeKit | `_hap._tcp` | 5710 |
| MyNice / NHK | `_nap._tcp` | 443 |

An NHK `CONFIG` with `<Mode>NHK</Mode>` (protocolType `WNC`) flips a module out of HomeKit
into MyNice. The MyNice app sends this when adding automations or changing Wi‑Fi, which is
why a HomeKit pairing can "spontaneously" stop working. This integration uses the MyNice /
NHK side.

## 3. Session handshake

```
VERIFY  (unsigned)  ->  <Authentication id="<userId>" .../>          # user lookup
CONNECT (unsigned)  ->  <Authentication id="<sessionId>" sc="…"/>    # sc = server challenge
```

**The session id comes from CONNECT, not VERIFY** (VERIFY's `id` is the *user* id). Using
VERIFY's id yields `<Code>3</Code>` "Sign or session error".

After CONNECT, every other command is **signed**:

```
session_pw = SHA256( pairing_pw_bytes, reverse(sc_bytes), reverse(cc_bytes) )
<Sign>     = base64( SHA256( SHA256(header + body), session_pw ) )
```

`<Sign>` is the last element in the request body.

## 4. Pairing and the password

`PAIR` with a **setup code** (`999‑99‑999`, dashes included) makes the caller the first
user = **administrator** — but only on a module with **no users** (`VERIFY` → code 10).

- **Setup‑code check attribute:**
  `check = uppercase 8‑hex of ~CRC32( setupCode + reverse(cc) + "Nice4U" )`
  (note the bitwise NOT, and the salt is **`Nice4U`**).
- **First‑pair response** carries **no `pwd`** — it returns a server challenge `sc`, and the
  pairing password is **derived**:
  `pairing_pw = SHA256( setupCode + reverse(sc) + reverse(cc) + "Nice" )`
  (here the trailing salt is **`Nice`**, not `Nice4U`). **Capture `cc` before sending** or
  you cannot reconstruct the password.
- A plain `PAIR` **without** a setup code returns a `pwd` immediately but creates a
  **pending** user (code 1) that an administrator must approve.

### User management (admin session)

- `PAIRINGS` → `<Users>` (confirmed) and `<PreAss>` (pending, `perm="wait"`).
- `USER_NEW` `<User id="…" username="…"/>` → approve a pending user.
- `USER_EDIT` `<User id="…" username="…" perm="admin|user|disable|delete"/>` → change role.

This is how the phone apps get authorised once Home Assistant holds admin: read `PAIRINGS`,
`USER_NEW` the pending entry.

## 5. Motor parameters — raw T4 / DMP tunnelling

Control‑unit parameters are **not** the `T4Action`/`DoorAction` service. They ride a second
command type, **`T4_REQUEST`**, carrying a tunnelled BusT4 frame with `<Protocol>DMP</Protocol>`.

Prologue, **per session** (raw messaging is off by default):

```
T4_STATUS                       -> <Interface><IAddr>50</IAddr><IEndp>10</IEndp><Status>0</Status>…
T4_CONFIG <Status>1</Status>    -> enable raw tunnelling
```

Then a DMP read:

```xml
<Interface id="1">
  <Protocol tout="2500">DMP</Protocol>
  <DAddress>00</DAddress><DEndpoint>03</DEndpoint>
  <T4 id="1" len="…" key="<base64 30‑char key>">base64( frame XOR sha256(key) )</T4>
</Interface>
```

- **Control‑unit target:** `DAddress=0x00`, `DEndpoint=0x03`.
- **Source address in the frame:** `iaddr = IAddr`, `iendp = IEndp | 0x80` (from `T4_STATUS`).
  Hardcoding `0x50/0x91` yields code 14.
- **Frame:** `0x55, len, daddr, dendp, iaddr, iendp, 0x08, sublen, marker, group, param, op,
  …, crc, len`, where `marker = iaddr ^ iendp ^ 0x08 ^ sublen ^ daddr ^ dendp`,
  op `0x99`=read / `0xA9`=write, reply op `0x19`.
- **Payload obfuscation:** `XOR` with `sha256(key)`, key sent in clear in the same document.

### ROBUS SG01a register map (group 0x04), as observed

| Reg | Meaning | Example |
|---|---|---|
| `04/01` | door state | 5 = closed |
| `04/11` | current encoder position | 0…3857 |
| `04/12`,`04/18` | learned travel / max open | 3857 |
| `04/21`–`04/23` | partial‑open 1/2/3 position | 1000 / 3000 / 4000 |
| `04/42`,`04/43` | opening / closing speed (%) | 100 / 100 |
| `04/4A`,`04/4B` | opening / closing force (%) | 85 / 85 |
| `04/B1` | total maneuver count | 46734 |
| `04/B2`,`04/B3` | maintenance counters | 5023 |

Percentage of open = `current_encoder / open_encoder * 100` (e.g. `387/3857 ≈ 10 %`). No
calibration profile needed — it's a direct measured ratio.

## 6. Radio transmitters — OXI / OXIBD receiver

The radio receiver is a separate BusT4 device reached through the same
`T4_REQUEST`/DMP tunnel, at **`DAddress=0x00`, `DEndpoint=0x0A`**, device/group
byte **`0x0A`**. Layouts recovered from the app's native `libnative-lib.so` and
cross‑checked against the community BusT4 projects (pruwait / makstech / gashtaan).

Unlike a control‑unit register read, a radio‑code message carries an explicit
`offset` and `length` byte between the op and the payload:

```
group param  op   offset len  <payload…>
0x0A  0x25   0x99 0x00   0x02 posHi posLo        # GET one code slot at position
0x0A  0x25   0xA9 0x00   0x0A <10‑byte record>   # SET one code slot (add/delete)
0x0A  0x26   0xA9 0x00   0x01 seconds            # SET learn‑mode window (0 = cancel)
0x0A  0x20   0xA9 0x00   0x01 0xFF               # SET erase‑all (0x01 codes, 0x02 +keys)
```

- **Reply form:** a code read answers `… 0A 25 01 0A 00 <10‑byte record> …`
  (op byte `0x01`, not the `0x19` register reply); the record starts at frame
  byte 14. Read positions `0…N`; a **virgin** record (`serial == 0x0FFFFFFF`)
  ends the used memory, an **empty** record (`serial/button/round == 0`) is a
  freed slot.
- **Per‑session read cap:** the interface rejects further raw reads after a
  handful on one session — tear the NHK session down and re‑establish it every
  few reads (this re‑enables raw T4).

### 10‑byte code record

```
[0:2] position (big‑endian; 0xFFFF on write = auto‑assign a free slot)
[2:5]+low nibble[5]  serial (28‑bit, little‑endian)
[5] high nibble       button (physical button)
[6:8] round           rolling‑code counter (little‑endian)
[8] high nibble       functionMode2 (button function, see map)   low nibble t4Group
[9] bit7..6 priority  bit5..4 remoteType (0 mono / 1 BiDi)        bits3..0 group abilitation
```

### functionMode2 → gate command (control‑unit receiver)

Index into the app's own function picker — **not** the DEP bus byte:

| code | command | code | command |
|---|---|---|---|
| 1 | Step by step | 8 | Partial opening 2 |
| 2 | Partial opening 1 | 9 | Partial opening 3 |
| 3 | Open | 10 / 11 | Open / Close and block |
| 4 | Close | 12 / 13 | Block / Release automation |
| 5 | Stop | 14 / 15 | Courtesy light timer / on‑off |
| 6 | Condominium step by step | 7 | Step by step high priority |

### Learn mode

SET param `0x26` to a seconds window (the app uses 100) and re‑arm it every
≤10 s while waiting; the receiver captures the next transmitter pressed nearby
and stores it (poll the code list for the new record, or watch for event status
`100`). Cancel with `0x26 = 0`. **Learn mode needs no key even on an OXIBD.**

> **OXIBD caveat.** Direct code writes (`0A/25` SET) may require the receiver's
> *O‑Manage* variant (an 11/12‑byte record and a session challenge) on an OXIBD;
> learn mode (`0x26`) side‑steps it and is the reliable way to add a remote.

## 7. Gotchas

- **One session at a time.** HA holding a session blocks the phone apps and vice‑versa.
  A stuck session answers **code 15**; power‑cycling the interface clears it.
- **Cloud vs local.** MyNice cloud stores per‑device credentials
  (`accessoryUser` is the real NHK username; `description` like `ANDROID_DEVICE` is just a
  label — don't confuse them). Local NHK auth is independent of the cloud connection state
  (orange L2 = no cloud, which does not affect local control).
- **A full config reset** wipes the user table; the interface then returns code 10 and the
  next `PAIR` with the setup code becomes admin again.
