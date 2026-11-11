"""Allowlisted public notification snapshots; never remote identity or free text."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class BookingNotificationSnapshot:
    booking_code: str
    bench_id: int
    starts_at: str
    ends_at: str
    status: str
    approval_status: str
    equipment_id: int | None = None
    inactive_at: str | None = None
    bench_name: str | None = None
    equipment_name: str | None = None

    def as_payload(self) -> dict:
        return asdict(self)


def scheduled_start_is_due(*, starts_at: datetime, ends_at: datetime, now: datetime) -> bool:
    return starts_at <= now < min(ends_at, starts_at + timedelta(minutes=10))


@dataclass(frozen=True, slots=True)
class SessionBookingFacts:
    """A booking's facts that decide whether a completed session used it."""

    booking_id: int
    bench_id: int
    starts_at: datetime
    ends_at: datetime
    status: str
    approval_status: str


@dataclass(frozen=True, slots=True)
class AgentBookingExtended:
    """A running booking the agent extended; ``ends_at`` is the new end."""

    booking_code: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class AgentBookingEnded:
    """A booking the agent ended at the user's request."""

    booking_code: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class AgentBookingLogin:
    """What an agent may know about a booking it is allowed to log a user in with."""

    booking_code: str
    starts_at: datetime
    ends_at: datetime
    booked_for: str | None
