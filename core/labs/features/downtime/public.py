"""Supported downtime commands and queries for other features (nothing imports this feature today)."""

from .application import (
    DowntimeActionInput,
    ScheduleDowntimeInput,
    cancel_downtime,
    end_downtime,
    schedule_downtime,
)
from .exceptions import DowntimeBookingConflict, DowntimeNotAllowed, DowntimeOverlap
from .queries import get_downtime, list_downtimes

__all__ = (
    "DowntimeActionInput",
    "DowntimeBookingConflict",
    "DowntimeNotAllowed",
    "DowntimeOverlap",
    "ScheduleDowntimeInput",
    "cancel_downtime",
    "end_downtime",
    "get_downtime",
    "list_downtimes",
    "schedule_downtime",
)
