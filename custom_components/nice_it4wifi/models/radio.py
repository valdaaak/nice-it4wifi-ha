"""Bounded models for radio-transmitter (OXI receiver) data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..protocol.t4.radio import radio_command_name


@dataclass(frozen=True, slots=True)
class NiceTransmitterButton:
    """One programmed button of a transmitter and the gate command it sends."""

    button: int
    command: int
    position: int | None = None
    round: int | None = None
    t4_group: int | None = None
    priority: int | None = None
    group_abilitation: int | None = None
    raw: str | None = None
    battery_level: int | None = None
    remote_protocol: int | None = None
    remote_model: int | None = None
    len12: bool = False

    def as_dict(self) -> dict[str, object]:
        """Serialize the button number, function code and its readable name.

        When the raw slot bytes are known the diagnostic fields of the record
        (slot position, rolling-code round, T4 group, priority, group abilitation
        and the raw record) are included as well. For a 12-byte "OMng" record the
        remote protocol and model are added; for a bidirectional remote the
        battery-level nibble is reported in place of the group abilitation.
        """
        data: dict[str, object] = {
            "button": self.button,
            "command": self.command,
            "command_name": radio_command_name(self.command),
        }
        if self.raw is not None:
            data.update(
                {
                    "position": self.position,
                    "round": self.round,
                    "t4_group": self.t4_group,
                    "priority": self.priority,
                    "group_abilitation": self.group_abilitation,
                    "raw": self.raw,
                }
            )
            if self.battery_level is not None:
                data["battery_level"] = self.battery_level
            if self.len12:
                data["remote_protocol"] = self.remote_protocol
                data["remote_model"] = self.remote_model
        return data


@dataclass(frozen=True, slots=True)
class NiceTransmitter:
    """One stored radio transmitter, aggregated across its buttons."""

    serial: int
    remote_type: int  # 0 = mono, 1 = bidirectional
    buttons: tuple[NiceTransmitterButton, ...]

    @property
    def is_bidi(self) -> bool:
        """Return whether the transmitter is bidirectional."""
        return self.remote_type == 1

    def as_dict(self) -> dict[str, object]:
        """Serialize identifying transmitter data for a service response."""
        return {
            "serial": self.serial,
            "serial_hex": f"{self.serial:06X}",
            "type": "bidi" if self.is_bidi else "mono",
            "buttons": [button.as_dict() for button in self.buttons],
        }


@dataclass(frozen=True, slots=True)
class NiceTransmitterSnapshot:
    """A bounded view of the transmitters stored in the radio receiver."""

    transmitters: tuple[NiceTransmitter, ...]
    record_count: int = 0
    retrieved_at: datetime | None = None

    @property
    def count(self) -> int:
        """Return the number of distinct transmitters."""
        return len(self.transmitters)

    @classmethod
    def from_records(cls, records) -> "NiceTransmitterSnapshot":
        """Aggregate decoded radio-code records into distinct transmitters.

        ``records`` is an iterable of objects exposing ``serial``, ``button``,
        ``command``, ``remote_type``, ``empty`` and ``virgin`` (RadioRecord).
        Empty and virgin slots are ignored; buttons of the same serial are merged.
        """
        order: list[int] = []
        functions: dict[int, dict[int, object]] = {}
        rtype: dict[int, int] = {}
        used = 0
        for record in records:
            if record.empty or record.virgin:
                continue
            used += 1
            if record.serial not in functions:
                functions[record.serial] = {}
                rtype[record.serial] = record.remote_type
                order.append(record.serial)
            functions[record.serial][record.button] = record
        transmitters = tuple(
            NiceTransmitter(
                serial=serial,
                remote_type=rtype[serial],
                buttons=tuple(
                    NiceTransmitterButton(
                        button=button,
                        command=record.command,
                        position=getattr(record, "position", None),
                        round=getattr(record, "round", None),
                        t4_group=getattr(record, "t4_group", None),
                        priority=getattr(record, "priority", None),
                        group_abilitation=getattr(record, "group_abilitation", None),
                        raw=getattr(record, "raw", None),
                        battery_level=(
                            getattr(record, "battery_level", None)
                            if getattr(record, "remote_type", 0) == 1
                            else None
                        ),
                        remote_protocol=getattr(record, "remote_protocol", None),
                        remote_model=getattr(record, "remote_model", None),
                        len12=getattr(record, "len12", False),
                    )
                    for button, record in sorted(functions[serial].items())
                ),
            )
            for serial in order
        )
        return cls(transmitters=transmitters, record_count=used)
