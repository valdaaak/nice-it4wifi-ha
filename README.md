# Nice IT4WIFI — Home Assistant integration

<img src="icon.png" width="96" align="right" alt="Nice logo">

Local control of **Nice gate & garage automations** through the older **IT4WIFI**
Wi‑Fi interface (BusT4), for Home Assistant.

This is an **IT4WIFI‑adapted fork** of
[**Jordi‑14/homeassistant_nice**](https://github.com/Jordi-14/homeassistant_nice),
which targets the newer **BiDi‑WiFi** interface. The upstream code already contains the
whole NHK/T4/DMP protocol layer — this fork adds the handful of fixes needed to make it
work on the **IT4WIFI** hardware and older control units such as the **Nice ROBUS**.

If you have a BiDi‑WiFi interface, use the upstream integration. Use this one if your
interface reports itself as **IT4WIFI** (`_nap._tcp`, model `Nice Spa - IT4WIFI - …`).

---

## What works

Verified on **IT4WIFI interface fw 0.4.43** (`SB575B‑R10.0`) + **Nice ROBUS `SG01a`**:

- `cover` entity — **open / close / stop / set position**, with the real state read from
  the encoder (not a time simulation)
- Live **open percentage** straight from the encoder ratio
- **Obstacle detection**
- **Motor parameters** (read & write): opening/closing speed & force, pause time,
  photo‑close, auto‑close, pre‑flash, standby, key‑lock, partial‑open positions 1–3
- Diagnostics: firmware/hardware/serial, maneuver & maintenance counters, motor
  temperature, last stop reason
- **Local** connection (TLS on port 443); optional cloud relay fallback

## Known limitations

- **Position calibration is not needed and is disabled by design.** The percentage is the
  exact encoder ratio; calibration tries to physically stop the gate mid‑travel, which a
  fast gate never lets it do (fails with *"stopped before reaching 20%"*). See
  [`docs/PROTOCOL.md`](docs/PROTOCOL.md).
- The interface handles **one NHK session at a time.** Close the MyNice / MyNice Pro app
  while Home Assistant is connected, and vice‑versa.
- Motor‑parameter register coverage depends on the control unit. On some units a few
  parameter entities stay unavailable (they simply aren't in that unit's register map).

---

## Installation (HACS)

1. HACS → three‑dot menu → **Custom repositories** → add this repository, category
   **Integration**.
2. Install **Nice IT4WIFI**, restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Nice IT4WIFI**.
4. Choose a connection mode and credential source:
   - **MyNice import** — log in with your MyNice account once; Home Assistant imports the
     per‑device NHK credentials and discards the account password/token.
   - **Manual** — enter the NHK username + 64‑hex password yourself.
5. Pick your interface from the list.

> **Close the MyNice/MyNice Pro app before validating the connection** — the interface
> serves a single session.

### First‑time pairing note

If the interface has no users yet, the **first** account to pair becomes the
administrator. Home Assistant pairs with your MyNice credentials; if you also want the
phone apps, an administrator authorises them afterwards. Details and the password
derivation are in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

---

## What this fork changes vs upstream v0.8.0

Six small, surgical fixes — full technical changelog in [`PATCHES.md`](PATCHES.md):

| File | Fix |
|---|---|
| `transport/lan.py` | TLS `OP_LEGACY_SERVER_CONNECT` + `SECLEVEL=0` (IT4WIFI has a 1024‑bit DH key and a pre‑RFC‑5746 stack) |
| `client.py` | tolerate NHK error code `5`; enable raw T4 tunnelling per session; use the interface‑reported source address |
| `coordinator.py` | tolerate code `5`; keep cached motor parameters instead of dropping them for one cycle |
| `protocol/t4/dmp.py` | pass the interface bus address into the DMP frame builders |
| `entity.py` | fix `KeyError` on `host` in cloud‑only mode |
| `position.py` | derive the open percentage from the live encoder ratio instead of a 1 %/s animation |

Reference: upstream issue
[Jordi‑14/homeassistant_nice#27](https://github.com/Jordi-14/homeassistant_nice/issues/27)
(IT4WIFI fw 0.4.43).

## Credits & license

- Upstream: [Jordi‑14/homeassistant_nice](https://github.com/Jordi-14/homeassistant_nice)
  — all of the heavy protocol work is theirs.
- Nice logo: from [home‑assistant/brands](https://github.com/home-assistant/brands).
- Same license as upstream — see [`LICENSE`](LICENSE).

Not affiliated with or endorsed by Nice S.p.A.
