"""Mathematical and calendar aggregation utilities for analytics projections."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
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

#: Observation count fields that measure a population at a point in time. Summing them across a
#: bucket would multiply the population by the number of snapshots, so buckets take the maximum.
POPULATION_COUNT_FIELDS = ("active_laboratory_count", "active_user_count")

#: Days returned by a daily series when the caller gives no range.
DEFAULT_DAILY_WINDOW_DAYS = 30
#: Longest daily series a caller may request (bounded read).
MAX_DAILY_WINDOW_DAYS = 366


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


def local_day_start(day: date) -> datetime:
    """Return the aware start of ``day`` in the current time zone (DST-correct)."""
    return timezone.make_aware(datetime.combine(day, time.min))


def resolve_daily_window(
    date_after: date | None,
    date_before: date | None,
    *,
    today: date,
) -> tuple[date, date]:
    """Resolve an inclusive-start, exclusive-end day window for a daily series.

    With no bounds the window is the last ``DEFAULT_DAILY_WINDOW_DAYS`` days including today.
    A missing end defaults to tomorrow (today included); a missing start defaults to
    ``DEFAULT_DAILY_WINDOW_DAYS`` before the end. Raises ``ValueError`` for an empty window or
    one longer than ``MAX_DAILY_WINDOW_DAYS``.
    """
    end = date_before if date_before is not None else today + timedelta(days=1)
    start = date_after if date_after is not None else end - timedelta(days=DEFAULT_DAILY_WINDOW_DAYS)
    if start >= end:
        raise ValueError("date_after must be before date_before.")
    if (end - start).days > MAX_DAILY_WINDOW_DAYS:
        raise ValueError(f"A daily series covers at most {MAX_DAILY_WINDOW_DAYS} days.")
    return start, end


def aggregate_observation_buckets(
    model: Any,
    unit: str,
    *,
    date_after: date | None = None,
    date_before: date | None = None,
) -> QuerySet:
    """Aggregate observation model metrics across standardized time buckets.

    ``date_after`` (inclusive) and ``date_before`` (exclusive) bound ``period_start`` by local
    calendar day; omitted bounds leave that side open.
    """
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
    count_agg = Max(count_field) if count_field in POPULATION_COUNT_FIELDS else Sum(count_field)

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
    queryset = model.objects.all()
    if date_after is not None:
        queryset = queryset.filter(**{f"{date_field}__gte": local_day_start(date_after)})
    if date_before is not None:
        queryset = queryset.filter(**{f"{date_field}__lt": local_day_start(date_before)})
    return (
        queryset.annotate(**mapping["annotation"])
        .values(*mapping["group_by"])
        .annotate(count=count_agg)
        .order_by(*mapping["order_by"])
    )


__all__ = [
    "DEFAULT_DAILY_WINDOW_DAYS",
    "MAX_DAILY_WINDOW_DAYS",
    "POPULATION_COUNT_FIELDS",
    "SLOT_LABELS",
    "aggregate_observation_buckets",
    "calculate_official_working_hours",
    "calculate_period_trend",
    "calculate_timeslot_distribution",
    "calculate_working_hours",
    "get_nearest_monday",
    "get_nearest_tuesday",
    "local_day_start",
    "resolve_daily_window",
]
