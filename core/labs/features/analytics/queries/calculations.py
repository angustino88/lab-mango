"""Mathematical and calendar aggregation utilities for analytics projections."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.db.models import Max, Sum
from django.db.models.functions import Extract, TruncDate
from django.utils import timezone

if TYPE_CHECKING:
    from django.db.models import QuerySet

SLOT_LABELS = (
    "00h-02h", "02h-04h", "04h-06h", "06h-08h",
    "08h-10h", "10h-12h", "12h-14h", "14h-16h",
    "16h-18h", "18h-20h", "20h-22h", "22h-00h",
)


def calculate_working_hours(from_date: datetime, to_date: datetime) -> float:
    """Calculate total elapsed weekday hours between two timestamps."""
    weekday_seconds: float = 0.0
    current = from_date

    while current.timestamp() < to_date.timestamp():
        next_date = datetime.combine(
            current.date() + timedelta(days=1),
            datetime.min.time(),
            current.tzinfo,
        )
        period_end = next_date if next_date.timestamp() < to_date.timestamp() else to_date

        if current.weekday() < 5:
            weekday_seconds += (period_end - current).total_seconds()

        current = period_end

    return weekday_seconds / 3600.0


def calculate_official_working_hours(from_date: datetime, to_date: datetime) -> float:
    """Calculate official laboratory operating hours (Mon-Fri 09:00 to 17:00)."""
    official_seconds: float = 0.0
    current = from_date

    while current.timestamp() < to_date.timestamp():
        next_date = datetime.combine(
            current.date() + timedelta(days=1),
            datetime.min.time(),
            current.tzinfo,
        )
        period_end = next_date if next_date.timestamp() < to_date.timestamp() else to_date

        if current.weekday() < 5:
            start_of_work = current.replace(hour=9, minute=0, second=0, microsecond=0)
            end_of_work = current.replace(hour=17, minute=0, second=0, microsecond=0)
            effective_start = max(current, start_of_work)
            effective_end = min(period_end, end_of_work)
            if effective_start < effective_end:
                official_seconds += (effective_end - effective_start).total_seconds()

        current = period_end

    return official_seconds / 3600.0


def calculate_timeslot_distribution(from_date: datetime, to_date: datetime) -> list[float]:
    """Partition weekday active duration into 12 two-hour time buckets."""
    slots = [0.0] * 12
    cur = from_date

    while cur < to_date:
        weekday = cur.weekday()
        if weekday >= 5:
            days_to_monday = 7 - weekday
            next_monday = (cur + timedelta(days=days_to_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if next_monday >= to_date:
                break
            cur = next_monday
            continue

        slot_idx = cur.hour // 2
        next_hour = ((slot_idx + 1) * 2) % 24
        slot_end = cur.replace(hour=next_hour, minute=0, second=0, microsecond=0)
        if next_hour == 0:
            slot_end += timedelta(days=1)

        actual_end = min(slot_end, to_date)
        slots[slot_idx] += (actual_end - cur).total_seconds() / 3600.0
        cur = actual_end

    return slots


def calculate_period_trend(previous_count: int, current_count: int) -> int:
    """Return the percentage change from ``previous_count`` to ``current_count``.

    Standard formula: ``(current - previous) / previous * 100``. When the previous
    period is zero there is no meaningful baseline, so the result is ``0`` for no
    change and ``100`` for any growth from zero.
    """
    if previous_count == 0:
        return 0 if current_count == 0 else 100
    return round((current_count - previous_count) / previous_count * 100)


def get_nearest_monday() -> datetime:
    """Return midnight of the current week's Monday."""
    today = timezone.localtime()
    return (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def get_nearest_tuesday() -> datetime:
    """Return midnight of the current week's Tuesday."""
    today = timezone.localtime()
    weekday = today.weekday()
    days_since = weekday - 1 if weekday >= 1 else weekday + 6
    return (today - timedelta(days=days_since)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def aggregate_observation_buckets(model: Any, unit: str) -> QuerySet:
    """Aggregate observation model metrics across standardized time buckets."""
    unit_key = unit.lower()
    valid_units = ("day", "week", "month", "quarter", "year")
    if unit_key not in valid_units:
        raise ValueError(f"Invalid unit '{unit}'. Must be one of: {', '.join(valid_units)}.")

    fields = {f.name for f in model._meta.get_fields()}

    if "booking_count" in fields:
        count_field = "booking_count"
    elif "active_laboratory_count" in fields:
        count_field = "active_laboratory_count"
    elif "active_user_count" in fields:
        count_field = "active_user_count"
    elif "distinct_visitor_count" in fields:
        count_field = "distinct_visitor_count"
    else:
        count_field = "id"

    date_field = "period_start" if "period_start" in fields else "created"
    count_agg = Max(count_field) if "active_laboratory_count" in fields else Sum(count_field)

    unit_mappings: dict[str, dict[str, Any]] = {
        "day": {
            "annotation": {"date": TruncDate(date_field)},
            "group_by": ["date"],
            "order_by": ["date"],
        },
        "week": {
            "annotation": {"year": Extract(date_field, "year"), "week": Extract(date_field, "week")},
            "group_by": ["year", "week"],
            "order_by": ["year", "week"],
        },
        "month": {
            "annotation": {"year": Extract(date_field, "year"), "month": Extract(date_field, "month")},
            "group_by": ["year", "month"],
            "order_by": ["year", "month"],
        },
        "quarter": {
            "annotation": {"year": Extract(date_field, "year"), "quarter": Extract(date_field, "quarter")},
            "group_by": ["year", "quarter"],
            "order_by": ["year", "quarter"],
        },
        "year": {
            "annotation": {"year": Extract(date_field, "year")},
            "group_by": ["year"],
            "order_by": ["year"],
        },
    }

    mapping = unit_mappings[unit_key]
    return (
        model.objects.annotate(**mapping["annotation"])
        .values(*mapping["group_by"])
        .annotate(count=count_agg)
        .order_by(*mapping["order_by"])
    )


__all__ = [
    "SLOT_LABELS",
    "aggregate_observation_buckets",
    "calculate_official_working_hours",
    "calculate_period_trend",
    "calculate_timeslot_distribution",
    "calculate_working_hours",
    "get_nearest_monday",
    "get_nearest_tuesday",
]
