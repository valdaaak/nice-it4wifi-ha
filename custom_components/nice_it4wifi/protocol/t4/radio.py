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
# Radio-activation (learn mode) register: SET a seconds window (0 = cancel),
# re-armed periodically while a new transmitter is expected. Works for mono and
# BiDi and needs no key/certificate step (unlike direct protected-memory writes).
RADIO_ACTIVATION_PARAM = 0x26
RADIO_ACTIVATION_SECONDS = 100
RADIO_ACTIVATION_REARM_SECONDS = 8
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
    """One decoded radio-code memory slot.

    A slot is stored by the receiver as either a 10-byte record (mono/Flor
    receivers) or a 12-byte "OMng" record (OXIBD and other bidirectional-capable
    receivers, which append ``remote_protocol`` and ``remote_model``). The
    receiver answers reads with whichever width it uses, so ``len12`` reflects
    the record width the receiver reported and tells the writer which form to
    write back (see ``encode_radio_record_omng``).

    byte[9] low nibble is overloaded by remote type: on a mono record it is the
    T4 abilitation group; on a bidirectional record it is the battery-level
    nibble (the app reports ``nibble // 4``) and the abilitation group reads 0.
    """

    position: int
    serial: int
    button: int
    command: int
    round: int
    remote_type: int
    t4_group: int
    priority: int
    group_abilitation: int
    raw: str
    empty: bool
    virgin: bool
    battery_level: int = 0
    remote_protocol: int = 0
    remote_model: int = 0
    len12: bool = False

    def as_dict(self) -> dict[str, object]:
        """Serialize a transmitter-button record for a service response."""
        data: dict[str, object] = {
            "serial": self.serial,
            "serial_hex": f"{self.serial:06X}",
            "button": self.button,
            "command": self.command,
            "command_name": radio_command_name(self.command),
            "type": "bidi" if self.remote_type == REMOTE_TYPE_BIDI else "mono",
        }
        if self.remote_type == REMOTE_TYPE_BIDI:
            data["battery_level"] = self.battery_level
        if self.len12:
            data["remote_protocol"] = self.remote_protocol
            data["remote_model"] = self.remote_model
        return data


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
    len12 = len(record) >= 12
    raw = record[: 12 if len12 else 10].hex()
    position = (record[0] << 8) | record[1]
    if record[2] == 0xFF and record[3] == 0xFF and record[4] == 0xFF:
        return RadioRecord(
            position=position,
            serial=0,
            button=0,
            command=0,
            round=0,
            remote_type=REMOTE_TYPE_MONO,
            t4_group=0,
            priority=0,
            group_abilitation=0,
            raw=raw,
            empty=False,
            virgin=True,
            len12=len12,
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
    # byte[9] low nibble: T4 abilitation group on a mono record, but the battery
    # level on a bidirectional one (the app reports nibble // 4 and forces the
    # abilitation group to 0). This is why a learned BD remote reads back with
    # that nibble non-zero (e.g. 0x0C -> battery level 3) even though the writer
    # always sends 0 there (T4AbilitationGroup(0)); the receiver fills it in.
    low_nibble = record[9] & 0x0F
    if remote_type == REMOTE_TYPE_MONO:
        group_abilitation = low_nibble
        battery_level = 0
    else:
        group_abilitation = 0
        battery_level = low_nibble // 4
    empty = serial == 0 and button == 0 and round_ == 0
    return RadioRecord(
        position=position,
        serial=serial,
        button=button,
        command=command,
        round=round_,
        remote_type=remote_type,
        t4_group=record[8] & 0x0F,
        priority=record[9] >> 6,
        group_abilitation=group_abilitation,
        raw=raw,
        empty=empty,
        virgin=False,
        battery_level=battery_level,
        remote_protocol=record[10] if len12 else 0,
        remote_model=record[11] if len12 else 0,
        len12=len12,
    )


def encode_radio_record(
    serial: int,
    button: int,
    command: int,
    *,
    remote_type: int = REMOTE_TYPE_MONO,
    round_: int = 0,
    t4_group: int = 0,
    priority: int = 0,
    group_abilitation: int = 0,
    position: int = 0xFFFF,
) -> list[int]:
    """Build the 10-byte radio-code record (position 0xFFFF = auto-assign)."""
    byte5 = ((serial >> 24) & 0x0F) | ((button & 0x0F) << 4)
    return [
        (position >> 8) & 0xFF,
        position & 0xFF,
        serial & 0xFF,
        (serial >> 8) & 0xFF,
        (serial >> 16) & 0xFF,
        byte5,
        round_ & 0xFF,
        (round_ >> 8) & 0xFF,
        ((command & 0x0F) << 4) | (t4_group & 0x0F),
        ((priority & 0x03) << 6) | ((remote_type & 0x03) << 4) | (group_abilitation & 0x0F),
    ]


def encode_radio_record_omng(
    serial: int,
    button: int,
    command: int,
    *,
    remote_protocol: int,
    remote_model: int,
    remote_type: int = REMOTE_TYPE_MONO,
    round_: int = 0,
    t4_group: int = 0,
    priority: int = 0,
    group_abilitation: int = 0,
    position: int = 0xFFFF,
) -> list[int]:
    """Build the 12-byte "OMng" radio-code record used by OXIBD-class receivers.

    This is the 10-byte record plus ``remote_protocol`` (byte[10]) and
    ``remote_model`` (byte[11]). Bidirectional ("BD") remotes only take effect
    when written in this form: the native ``setCodeOMng`` encoder emits a 12-slot
    record, and a receiver that reports 12-byte records on read will not act on a
    10-byte write. ``group_abilitation`` is normally 0 for these records (the app
    passes ``T4AbilitationGroup(0)``); the receiver fills the battery nibble.
    """
    return [
        *encode_radio_record(
            serial,
            button,
            command,
            remote_type=remote_type,
            round_=round_,
            t4_group=t4_group,
            priority=priority,
            group_abilitation=group_abilitation,
            position=position,
        ),
        remote_protocol & 0xFF,
        remote_model & 0xFF,
    ]


def _build_radio_set_frame(
    record: list[int],
    iaddr: int,
    iendp: int,
    *,
    daddr: int = RADIO_TARGET_ADDR,
    dendpoint: int = RADIO_TARGET_ENDPOINT,
) -> bytes:
    args = [RADIO_GROUP, RADIO_CODE_PARAM, 0xA9, 0x00, len(record), *record]
    sublen = len(args) + 1
    marker = iaddr ^ iendp ^ 0x08 ^ sublen ^ daddr ^ dendpoint
    body = [daddr, dendpoint, iaddr, iendp, 0x08, sublen, marker, *args, dmp_checksum(*args)]
    length = len(body)
    return bytes([0x55, length, *body, length])


def build_radio_delete_frame(
    position: int,
    iaddr: int,
    iendp: int,
    *,
    daddr: int = RADIO_TARGET_ADDR,
    dendpoint: int = RADIO_TARGET_ENDPOINT,
) -> bytes:
    """Build a DMP SET frame that frees (deletes) one radio-code slot."""
    if not 0 <= position <= 0xFFFF:
        raise ValueError("position must fit in 16 bits")
    record = [(position >> 8) & 0xFF, position & 0xFF, 0, 0, 0, 0, 0, 0, 0, 0]
    return _build_radio_set_frame(
        record, iaddr, iendp, daddr=daddr, dendpoint=dendpoint
    )


def build_radio_add_frame(
    record: list[int],
    iaddr: int,
    iendp: int,
    *,
    daddr: int = RADIO_TARGET_ADDR,
    dendpoint: int = RADIO_TARGET_ENDPOINT,
) -> bytes:
    """Build a DMP SET frame that writes one radio-code record.

    Accepts a 10-byte record or a 12-byte "OMng" record (bidirectional-capable
    receivers); the DMP data length is taken from the record itself.
    """
    if len(record) not in (10, 12):
        raise ValueError("record must be 10 or 12 bytes")
    return _build_radio_set_frame(
        record, iaddr, iendp, daddr=daddr, dendpoint=dendpoint
    )


def build_radio_activation_frame(
    seconds: int,
    iaddr: int,
    iendp: int,
    *,
    daddr: int = RADIO_TARGET_ADDR,
    dendpoint: int = RADIO_TARGET_ENDPOINT,
) -> bytes:
    """Build a DMP SET frame that arms (seconds>0) or cancels (0) learn mode."""
    if not 0 <= seconds <= 0xFF:
        raise ValueError("seconds must fit in a byte")
    args = [RADIO_GROUP, RADIO_ACTIVATION_PARAM, 0xA9, 0x00, 1, seconds & 0xFF]
    sublen = len(args) + 1
    marker = iaddr ^ iendp ^ 0x08 ^ sublen ^ daddr ^ dendpoint
    body = [daddr, dendpoint, iaddr, iendp, 0x08, sublen, marker, *args, dmp_checksum(*args)]
    length = len(body)
    return bytes([0x55, length, *body, length])


# --- Radio activation (learn-mode) capture ---------------------------------
# While learn mode is armed (build_radio_activation_frame), the receiver reports
# each remote pressed nearby as an UNSOLICITED event carrying a CodR data region.
# The press is NOT written to the 0x25 code list, so it is caught on the event
# stream, not by polling the list. This layout is the native decodeCodR port and
# is BIG-endian, unlike the little-endian 0x25 code record.
RADIO_ACTIVATION_STATUS = 0x64  # EVT_RADIO_ACTIVATION wire value ("code acquired")


@dataclass(frozen=True, slots=True)
class RadioActivation:
    """One remote press captured while learn mode is armed."""

    serial: int
    button: int
    round: int
    priority: int
    in_memory: bool
    page: int
    memory_position: int
    remote_protocol: int
    remote_model: int
    len10: bool

    def as_dict(self) -> dict[str, object]:
        """Serialize a captured remote press."""
        return {
            "serial": self.serial,
            "serial_hex": f"{self.serial:06X}",
            "button": self.button,
            "round": self.round,
            "priority": self.priority,
            "in_memory": self.in_memory,
            "page": self.page,
            "memory_position": self.memory_position,
            "remote_protocol": self.remote_protocol,
            "remote_model": self.remote_model,
            "len10": self.len10,
        }


def decode_radio_activation_data(data: bytes) -> RadioActivation | None:
    """Decode the CodR data region of a radio-activation event (BIG-endian).

    8 bytes = mono (no protocol/model); 10 bytes = bidirectional/len10 record.
    Port of the app's native ``decodeCodR``: ``button = data[0] >> 4``; the 28-bit
    serial spans ``data[0]`` low nibble through ``data[3]``; ``round`` is a 16-bit
    big-endian value at ``data[4:6]``; ``data[6]`` packs priority (bits 7..6),
    in-memory (bit 2) and page (bits 1..0); ``data[7]`` is the memory slot; a
    10-byte record adds ``data[8]`` protocol and ``data[9]`` model.
    """
    if len(data) not in (8, 10):
        return None
    len10 = len(data) == 10
    return RadioActivation(
        serial=((data[0] & 0x0F) << 24) | (data[1] << 16) | (data[2] << 8) | data[3],
        button=data[0] >> 4,
        round=(data[4] << 8) | data[5],
        priority=data[6] >> 6,
        in_memory=bool(data[6] & 0x04),
        page=data[6] & 0x03,
        memory_position=data[7],
        remote_protocol=data[8] if len10 else 0,
        remote_model=data[9] if len10 else 0,
        len10=len10,
    )


def decode_radio_activation_frame(plain: bytes) -> RadioActivation | None:
    """Best-effort decode of a decrypted unsolicited frame as a remote press.

    Returns None for anything that is not a radio-group payload. The exact data
    offset is confirmed by a live capture; this reuses the code-list reply framing
    (data between the 14-byte header and 2-byte trailer) and skips a 0x25 code
    reply so a read is never mistaken for a press. Revalidate against the first
    captured payload before relying on the decoded values.
    """
    if len(plain) < 22 or plain[0] != 0x55 or plain[9] != RADIO_GROUP:
        return None
    if plain[10] == RADIO_CODE_PARAM:  # a code-list reply, not an activation
        return None
    data = plain[14 : len(plain) - 2]
    for width in (10, 8):
        if len(data) >= width:
            decoded = decode_radio_activation_data(bytes(data[:width]))
            if decoded is not None:
                return decoded
    return None
