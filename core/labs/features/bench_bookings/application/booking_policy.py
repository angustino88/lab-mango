"""The bench booking rules that apply to one caller, read from the constants and settings the commands use."""

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from core.users.public import LabsPermission, has_permission

from . import policies
from .slot_watches import MAX_ACTIVE_WATCHES_PER_USER


@dataclass(frozen=True, slots=True)
class SlotWatchPolicy:
    is_enabled: bool
    lead_minutes: int
    max_active: int


@dataclass(frozen=True, slots=True)
class BenchBookingPolicy:
    time_zone: str
    min_duration_minutes: int
    start_grace_minutes: int
    approval_required_above_minutes: int
    max_horizon_days: int | None
    is_computing_required: bool
    can_book_during_operator_downtime: bool
    can_manage_others_bookings: bool
    can_approve: bool
    slot_watch: SlotWatchPolicy


def _minutes(delta) -> int:
    return int(delta.total_seconds() // 60)


def get_bench_booking_policy(*, actor: Any) -> BenchBookingPolicy:
    """No query: constants, settings and the caller's permissions. ``max_horizon_days`` is ``None`` (no limit)."""
    return BenchBookingPolicy(
        time_zone=settings.TIME_ZONE,
        min_duration_minutes=_minutes(policies.MIN_BOOKING_DURATION),
        start_grace_minutes=_minutes(policies.START_GRACE),
        approval_required_above_minutes=_minutes(policies.LONG_BOOKING_APPROVAL_THRESHOLD),
        max_horizon_days=None,
        is_computing_required=True,
        can_book_during_operator_downtime=has_permission(actor, LabsPermission.BENCH_BOOKING_BOOK_DURING_DOWNTIME),
        can_manage_others_bookings=has_permission(actor, LabsPermission.BENCH_BOOKING_MANAGE_ANY),
        can_approve=has_permission(actor, LabsPermission.BENCH_BOOKING_APPROVE),
        slot_watch=SlotWatchPolicy(
            is_enabled=bool(getattr(settings, "BOOKING_SLOT_WATCH_ENABLED", False)),
            lead_minutes=int(getattr(settings, "BOOKING_SLOT_WATCH_LEAD_MINUTES", 15)),
            max_active=MAX_ACTIVE_WATCHES_PER_USER,
        ),
    )
