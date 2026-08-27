"""Bounded models for shared Wi-Fi administration data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NiceLogEvent:
    """One allowlisted event returned by the interface log."""

    scope: str
    event_type: str
    time: str | None = None
    door_action: str | None = None
    t4_action: str | None = None
    door_status: str | None = None
    obstruct: str | None = None

    def as_dict(self) -> dict[str, str]:
        """Serialize only reviewed, non-identifying protocol fields."""
        values = {
            "scope": self.scope,
            "event_type": self.event_type,
            "time": self.time,
            "door_action": self.door_action,
            "t4_action": self.t4_action,
            "door_status": self.door_status,
            "obstruct": self.obstruct,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class NiceLogSnapshot:
    """A bounded interface and device log result."""

    events: tuple[NiceLogEvent, ...]
    retrieved_at: datetime | None = None

    @property
    def count(self) -> int:
        """Return the number of retained events."""
        return len(self.events)


@dataclass(frozen=True, slots=True)
class NiceGroupSummary:
    """A redacted summary of one local access group."""

    ordinal: int
    interface_rule_count: int
    device_count: int
    device_rule_count: int

    def as_dict(self) -> dict[str, int]:
        """Serialize counts without group, device, or permission identifiers."""
        return {
            "ordinal": self.ordinal,
            "interface_rule_count": self.interface_rule_count,
            "device_count": self.device_count,
            "device_rule_count": self.device_rule_count,
        }


@dataclass(frozen=True, slots=True)
class NiceGroupSnapshot:
    """A bounded, read-only summary of local access groups."""

    groups: tuple[NiceGroupSummary, ...]
    retrieved_at: datetime | None = None

    @property
    def count(self) -> int:
        """Return the number of retained groups."""
        return len(self.groups)


@dataclass(frozen=True, slots=True)
class NiceUser:
    """One user account paired to the interface.

    Unlike the redacted group summaries, user management inherently needs the
    account name to be actionable, so this fork exposes it — but only through
    on-demand service responses, never persisted entity state or diagnostics.
    """

    username: str
    user_id: int | None = None
    permission: str | None = None
    pending: bool = False

    def as_dict(self) -> dict[str, str | int | bool]:
        """Serialize the fields needed to identify and manage a user."""
        values: dict[str, str | int | bool | None] = {
            "user_id": self.user_id,
            "username": self.username,
            "permission": self.permission,
            "pending": self.pending,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class NiceUserSnapshot:
    """A bounded view of confirmed and pending interface users."""

    users: tuple[NiceUser, ...]
    retrieved_at: datetime | None = None

    @property
    def count(self) -> int:
        """Return the number of retained users."""
        return len(self.users)

    @property
    def pending_count(self) -> int:
        """Return the number of users awaiting administrator approval."""
        return sum(1 for user in self.users if user.pending)


@dataclass(frozen=True, slots=True)
class NiceInterfaceClock:
    """NHK interface clock fields."""

    date: str
    zone: str
    dst: str


@dataclass(frozen=True, slots=True)
class NiceAdministrationOperation:
    """One privacy-safe administration operation result."""

    action: str
    status: str
    read_only: bool
    route: str
    latency_ms: int
    completed_at: datetime
    verification: str
    error_type: str | None = None
    error_code: str | None = None

    def as_diagnostics(self) -> dict[str, str | int | bool | None]:
        """Serialize a stable allowlist for diagnostics."""
        return {
            "action": self.action,
            "status": self.status,
            "read_only": self.read_only,
            "route": self.route,
            "latency_ms": self.latency_ms,
            "completed_at": self.completed_at.isoformat(),
            "verification": self.verification,
            "error_type": self.error_type,
            "error_code": self.error_code,
        }
