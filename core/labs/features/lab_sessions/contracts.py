"""Types returned across the lab sessions boundary."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SessionLogRecord:
    """A stored session log; ``created`` is False when the push was a replay of a stored record.

    ``access_type`` is None only for a replay of a row stored before access types existed.
    """

    id: int
    event_id: UUID
    login_time: datetime
    logout_time: datetime
    booking_code: str | None
    access_type: str | None
    created: bool


__all__ = ["SessionLogRecord"]
