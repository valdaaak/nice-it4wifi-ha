# PATCHES — what this fork changes vs upstream v0.8.0

Six fixes on top of [Jordi‑14/homeassistant_nice](https://github.com/Jordi-14/homeassistant_nice)
`v0.8.0`, so the integration works on a **Nice IT4WIFI** interface (fw 0.4.43,
`SB575B‑R10.0`) driving a **Nice ROBUS `SG01a`** control unit.

Each fix is one small, isolated change. Nothing else in the upstream code is touched.

---

## NHK error codes (context)

The interface answers commands with `<Error><Code>N</Code></Error>`. Meanings observed
(and confirmed against the MyNice app's own strings):

| Code | Meaning |
|---|---|
| 1 | user not registered / awaiting administrator confirmation (routing signal, **not** a hard error) |
| 2 | user disabled |
| 5 | command not allowed (also returned while raw T4 tunnelling is off) |
| 10 | accessory not yet paired with any user |
| 12 | user already registered |
| 14 | frame unroutable (wrong source address) |
| 15 | accessory not ready (busy) — power‑cycle if stuck |

---

## 1. `transport/lan.py` — TLS for a legacy stack

The IT4WIFI has a **1024‑bit Diffie‑Hellman key** and a TLS stack **without RFC 5746**
(secure renegotiation). Modern OpenSSL refuses both, so every connection failed with
`DH_KEY_TOO_SMALL` / `UNSAFE_LEGACY_RENEGOTIATION_DISABLED` before a single byte of NHK.

```python
context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
context.set_ciphers("DEFAULT:@SECLEVEL=0")
```

Result: `TLSv1.2 / DHE-RSA-AES256-SHA256` handshakes succeed.

## 2. `client.py` — code 5 tolerance + raw T4 enable + source address

Two problems on IT4WIFI:

- **Raw T4 tunnelling is off by default and must be enabled per session.** Without it,
  every DMP register read answers **code 5**. The fix sends `T4_STATUS` (to read the
  interface's own bus address) and `T4_CONFIG` with `<Status>1</Status>` right after
  authentication.
- **The source address in the DMP frame was hardcoded** to `0x50 / 0x91`. The IT4WIFI
  reports its real address via `T4_STATUS` (`IAddr` / `IEndp`); the source endpoint must
  be `IEndp | 0x80`. With the wrong endpoint every frame returned **code 14** (unroutable).

The read/status paths also now tolerate **code 5** alongside code 14 as a soft failure.

## 3. `coordinator.py` — code 5 tolerance + keep cached parameters

- Same **code 5** tolerance in the status‑poll fallback.
- Two return paths handed back a fresh NHK status **without re‑merging the cached extended
  (BusT4) parameters**, so every time a DMP read hiccuped, all the motor‑parameter
  entities went `unavailable` for one cycle and flapped. The fix wraps those returns in
  `_merge_cached_extended_status(...)`.

## 4. `protocol/t4/dmp.py` — parametrise the bus address

`build_dmp_read_frame` / `build_dmp_write_frame` had the source address baked in. They now
take `iaddr` / `iendp` keyword arguments (defaulting to the old `0x50 / 0x91`) so the
client can pass the interface‑reported address from fix #2. The frame marker byte is
computed from them: `marker = iaddr ^ iendp ^ 0x08 ^ sublen ^ daddr ^ dendp`.

## 5. `entity.py` — cloud‑only `KeyError`

`bidi_device_info` built `configuration_url=f"https://{entry.data[CONF_HOST]}"`. In
**cloud‑only** mode the config entry has no `host` key (only `relay_host`), so this raised
`KeyError` and Home Assistant refused to add **every** entity. Guarded with
`entry.data.get(CONF_HOST)`.

## 6. `position.py` — real encoder percentage

The percentage is already the exact encoder ratio (`current / open`). But
`position_snapshot` fed `resolve_position` an **optimistic 1 %/s animation** that overrode
it during movement. On a fast gate the display crawled 1 %, 2 %, 3 %… then snapped. The
fix suppresses the animation when live encoder data is present, so the percentage is the
measured value at rest and in motion.

---

## 7. `services.py` — user management (fork addition)

Beyond the six compatibility fixes, this fork adds a small service layer over the
NHK `PAIRINGS` / `USER_NEW` / `USER_EDIT` commands (the upstream integration has no
service layer at all). Four Home Assistant services — `list_users` (response data),
`approve_user`, `set_user_permission`, `delete_user` — let an administrator approve
a newly paired phone and manage roles from Home Assistant instead of the MyNice app.

The services refuse to delete or downgrade the account Home Assistant authenticates
with, preventing self-lockout, and verify each mutation with a `PAIRINGS` round-trip.
Reusing the existing signed-exchange, reconnect-wrapper, and snapshot machinery, the
change is additive: new `read_pairings` / `approve_user` / `edit_user` on the client
and router, `parse_pairings_xml` / `build_user_*_body` in `protocol/nhk/administration.py`,
`NiceUser` / `NiceUserSnapshot` models, user methods on the administration controller,
and `services.py` + `services.yaml`. Account names are exposed only through the
on-demand `list_users` response — never persisted entity state or diagnostics.

---

## 8. `protocol/t4/radio.py` + `list_transmitters` service (fork addition)

Lists the transmitters stored in the OXI/OXIBD radio receiver over BusT4 — the
receiver-management the MyNice app drops for IT4WIFI. A radio-code read is a DMP
GET to the receiver (daddr `0x00` / dendp `0x0A`, group `0x0A`, param `0x25`) but,
unlike a control-unit register read, its message body carries a 2-byte position
payload (`op, 0x00 seq, 0x02 datalen, posHi, posLo`) and the receiver answers
with `op=0x01` (not the `0x19` GET reply) — so it gets its own frame builder and
decoder (`build_radio_read_frame` / `decode_radio_record`). The record layout
(serial 28-bit, button in the serial's top nibble, round, mono/bidi type) was
recovered by disassembling the app's native `libnative-lib.so` and cross-checked
against the pruwait/makstech BusT4 projects.

The client enumerates positions 0…N, **recycling the NHK session every few reads**
because the interface rejects further raw reads after a handful on one session;
it stops at the first virgin slot. Exposed read-only as
`nice_it4wifi.list_transmitters` (response data); no add/delete.

---

## 9. Radio transmitter write + learn services (fork addition)

Beyond listing, the fork can manage the receiver's transmitter memory:
`add_transmitter` (by serial), `delete_transmitter` (returns removed records for
restore), `set_transmitter_command` (reassign a button's function), and
`learn_transmitter` (arm the receiver and capture a remote pressed on-site). All
ride DMP SET to the OXI (group `0x0A`, param `0x25` for codes, `0x26` for the
learn-mode activation window — re-armed periodically), each verified by reading
the memory back. The frame/record layout and the activation register were
recovered by disassembling the app's native `libnative-lib.so`. Learn mode needs
no key even on an OXIBD; direct code writes on an OXIBD may need the O-Manage /
challenge variant (not implemented) — hence learn mode is the recommended add path.

---

## 10. `protocol/t4/live.py` — direction comes from NHK `DoorStatus` only

The interface wraps raw T4 bus traffic into its CHANGE events and upstream decodes
the `04/40` live payload (state byte + instant position) and `04/02` (state byte)
into the cover state. On the SG01a the `04/40` state byte reports **`opening` while
the gate is closing** (its position is mirrored the same way: ~97 % at the closed
endpoint), while the NHK `DoorStatus` in the same stream is correct. The two sources
overwrote each other once a second — `closing` from `DoorStatus` for a few hundred
milliseconds, then `opening` from `04/40` — so `cover.brana` sat in `opening` for the
whole closing run and anything triggered on `to: opening` fired on every close.

Fix: a live T4 payload never applies `opening`/`closing`. `04/40` contributes position
only, `04/02` only its terminal states (`open`/`closed`/`stopped`, which match reality).
`DoorStatus` alone decides the direction. The `NHK/T4StatusIgnored` register now names
the reason (`04/40_position_only`, `04/02_direction_ignored`) and `state_source` no
longer reports `t4_04_40_motion`.

---

## Note on calibration

Position calibration is **not needed** on encoder gates and **fails** on a fast gate
(it tries to physically stop the gate at 20/40/60/80 %, but a gate that crosses its full
travel in seconds reaches the endpoint before the 0.5 s poll can stop it → *"stopped
before reaching 20%"*). This fork leaves calibration in place but relies on the encoder
ratio instead; the calibrate button can stay hidden. See
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the mechanics.
