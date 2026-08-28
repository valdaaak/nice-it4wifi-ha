"""Radio-transmitter (OXI receiver) memory access over BusT4/DMP.

The OXI/OXIBD radio receiver stores each transmitter button as a record in a
sequential memory. Unlike control-unit register reads, a radio-code read carries
a 2-byte position payload (``datalen=0x02``) and the receiver answers with a
distinct message form (``op=0x01``, not the ``0x19`` GET reply), so it needs its
own frame builder and decoder rather than the generic DMP register helpers.

Reverse-engineered from the MyNice Pro native library (``RadioQueryMemory`` /
``RadioQueryMemoryResult``) and cross-checked against the community BusT4
projects (pruwait/ngem1/makstech: group ``0x0A`` = OXI, param ``0x25`` = code list).
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import dmp_checksum

# The OXI radio receiver answers DMP at bus address 0x00 / endpoint 0x0A.
RADIO_TARGET_ADDR = 0x00
RADIO_TARGET_ENDPOINT = 0x0A
# Device-target ("whose") byte and the code-in-memory register.
RADIO_GROUP = 0x0A
RADIO_CODE_PARAM = 0x25
# Safety bound and per-session read budget: the interface rejects further raw
# reads after a handful on one session, so the caller recycles the session.
RADIO_MAX_POSITIONS = 64
RADIO_READ_RECYCLE = 4

REMOTE_TYPE_MONO = 0
REMOTE_TYPE_BIDI = 1

# Mode-2 button function code -> gate command name. The code is the index into
# the app's own function picker for a control-unit receiver (not the DEP bus
# byte, which uses a different numbering). Labels from the MyNice Pro resources.
RADIO_COMMAND_NAMES = {
    0: "None",
    1: "Step by step",
    2: "Partial opening 1",
    3: "Open",
    4: "Close",
    5: "Stop",
    6: "Condominium step by step",
    7: "Step by step high priority",
    8: "Partial opening 2",
    9: "Partial opening 3",
    10: "Open and block",
    11: "Close and block",
    12: "Block automation",
    13: "Release automation",
    14: "Courtesy light timer",
    15: "Courtesy light on/off",
}


def radio_command_name(code: int) -> str:
    """Return the human-readable name of a Mode-2 button function code."""
    return RADIO_COMMAND_NAMES.get(code, f"command {code}")


def build_radio_read_frame(
    position: int,
    iaddr: int,
    iendp: int,
    *,
    daddr: int = RADIO_TARGET_ADDR,
    dendpoint: int = RADIO_TARGET_ENDPOINT,
) -> bytes:
    """Build a DMP GET frame that reads one radio-code memory slot."""
    if not 0 <= position <= 0xFFFF:
        raise ValueError("position must fit in 16 bits")
    payload = [(position >> 8) & 0xFF, position & 0xFF]
    args = [RADIO_GROUP, RADIO_CODE_PARAM, 0x99, 0x00, len(payload), *payload]
    sublen = len(args) + 1
    marker = iaddr ^ iendp ^ 0x08 ^ sublen ^ daddr ^ dendpoint
    body = [
        daddr,
        dendpoint,
        iaddr,
        iendp,
        0x08,
        sublen,
        marker,
        *args,
        dmp_checksum(*args),
    ]
    length = len(body)
    return bytes([0x55, length, *body, length])


@dataclass(frozen=True, slots=True)
class RadioRecord:
    """One decoded radio-code memory slot."""

    position: int
    serial: int
    button: int
    command: int
    round: int
    remote_type: int
    empty: bool
    virgin: bool


def decode_radio_record(plain: bytes) -> RadioRecord | None:
    """Decode a decrypted radio-code reply frame into a slot record.

    Returns ``None`` when the frame is not a radio-code reply. A ``virgin``
    record marks the end of the used memory; an ``empty`` record is a freed slot.
    """
    if (
        len(plain) < 24
        or plain[0] != 0x55
        or plain[9] != RADIO_GROUP
        or plain[10] != RADIO_CODE_PARAM
    ):
        return None
    record = plain[14 : len(plain) - 2]
    if len(record) < 10:
        return None
    position = (record[0] << 8) | record[1]
    if record[2] == 0xFF and record[3] == 0xFF and record[4] == 0xFF:
        return RadioRecord(
            position=position,
            serial=0,
            button=0,
            command=0,
            round=0,
            remote_type=REMOTE_TYPE_MONO,
            empty=False,
            virgin=True,
        )
    serial = (
        record[2]
        | (record[3] << 8)
        | (record[4] << 16)
        | ((record[5] & 0x0F) << 24)
    )
    button = record[5] >> 4
    command = record[8] >> 4
    round_ = record[6] | (record[7] << 8)
    remote_type = (record[9] >> 4) & 0x03
    empty = serial == 0 and button == 0 and round_ == 0
    return RadioRecord(
        position=position,
        serial=serial,
        button=button,
        command=command,
        round=round_,
        remote_type=remote_type,
        empty=empty,
        virgin=False,
    )
