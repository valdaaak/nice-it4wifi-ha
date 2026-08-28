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

    def as_dict(self) -> dict[str, object]:
        """Serialize the button number, function code and its readable name."""
        return {
            "button": self.button,
            "command": self.command,
            "command_name": radio_command_name(self.command),
        }


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
        functions: dict[int, dict[int, int]] = {}
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
            functions[record.serial][record.button] = record.command
        transmitters = tuple(
            NiceTransmitter(
                serial=serial,
                remote_type=rtype[serial],
                buttons=tuple(
                    NiceTransmitterButton(button=button, command=command)
                    for button, command in sorted(functions[serial].items())
                ),
            )
            for serial in order
        )
        return cls(transmitters=transmitters, record_count=used)
