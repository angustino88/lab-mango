"""Read-only queries for aggregate volume and population observations."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.labs.models import (
    ActiveLaboratoryObservation,
    ActiveUserObservation,
    Bench,
    BenchBooking,
    BookingVolumeObservation,
    LaboratoryVisitEvent,
    VisitorVolumeObservation,
)

from .calculations import (
    aggregate_observation_buckets,
    calculate_period_trend,
    local_day_start,
    resolve_daily_window,
)

MetricResult = dict[str, Any] | list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Live counts. Shared by the daily snapshot tasks and by "today" in a daily series, so a
# snapshot and the live value for the same day always use the same definition.
# ---------------------------------------------------------------------------


def count_bookings_created(start: datetime, end: datetime) -> int:
    """Count bookings created in ``[start, end)``."""
    return BenchBooking.objects.filter(created__gte=start, created__lt=end).count()


def count_distinct_visitors(start: datetime, end: datetime) -> int:
    """Count distinct visitors with a visit event in ``[start, end)``.

    Visits without a known visitor (anonymous or removed accounts) count as one visitor,
    matching the historical snapshot definition.
    """
    return (
        LaboratoryVisitEvent.objects.filter(occurred_at__gte=start, occurred_at__lt=end)
        .values("visitor")
        .distinct()
        .count()
    )


def count_active_users() -> int:
    """Count user accounts that are currently active."""
    return get_user_model().objects.filter(is_active=True).count()


def count_active_benches() -> int:
    """Count benches that are currently not deleted."""
    return Bench.objects.filter(deleted_at__isnull=True).count()


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return local_day_start(day), local_day_start(day + timedelta(days=1))


def _daily_series(
    model: Any,
    *,
    date_after: date | None,
    date_before: date | None,
    live_today: Callable[[date], int],
    fill_missing_with_zero: bool,
) -> list[dict[str, Any]]:
    """Return one ``{"date", "count"}`` row per local day in a bounded window, oldest first.

    Past days come from daily observations. Today has no snapshot yet (the nightly task records
    the day that just ended), so today's value is counted live. Future days are omitted.
    With ``fill_missing_with_zero`` (volumes) a past day without a snapshot reads as 0, so charts
    get a continuous axis; run the backfill command for days before the schedule existed.
    Population counts leave such days out, because 0 would wrongly read as "nobody".
    """
    today = timezone.localdate()
    start, end = resolve_daily_window(date_after, date_before, today=today)
    counts: dict[date, int] = {
        row["date"]: row["count"]
        for row in aggregate_observation_buckets(model, "day", date_after=start, date_before=end)
    }
    if start <= today < end:
        counts[today] = live_today(today)

    series: list[dict[str, Any]] = []
    day = start
    last_day = min(end, today + timedelta(days=1))
    while day < last_day:
        if day in counts:
            series.append({"date": day.isoformat(), "count": counts[day]})
        elif fill_missing_with_zero:
            series.append({"date": day.isoformat(), "count": 0})
        day += timedelta(days=1)
    return series


def _bucketed(
    model: Any,
    unit: str,
    *,
    date_after: date | None,
    date_before: date | None,
    live_today: Callable[[date], int],
    fill_missing_with_zero: bool,
) -> list[dict[str, Any]]:
    if unit.lower() == "day":
        return _daily_series(
            model,
            date_after=date_after,
            date_before=date_before,
            live_today=live_today,
            fill_missing_with_zero=fill_missing_with_zero,
        )
    return list(aggregate_observation_buckets(model, unit, date_after=date_after, date_before=date_before))


def get_booking_volume_metrics(
    *,
    unit: str | None = None,
    date_after: date | None = None,
    date_before: date | None = None,
) -> MetricResult:
    """Retrieve booking volume trend or historical time-bucketed aggregates."""
    if unit:
        return _bucketed(
            BookingVolumeObservation,
            unit,
            date_after=date_after,
            date_before=date_before,
            live_today=lambda day: count_bookings_created(*_day_bounds(day)),
            fill_missing_with_zero=True,
        )

    now = timezone.now()
    this_week = now - timedelta(days=7)
    last_week = now - timedelta(days=14)

    current_count = BenchBooking.objects.filter(
        created__gte=this_week,
        created__lte=now,
    ).count()

    previous_count = BenchBooking.objects.filter(
        created__gte=last_week,
        created__lt=this_week,
    ).count()

    if current_count == 0 and previous_count == 0:
        obs = BookingVolumeObservation.objects.filter(period_start__gte=last_week)
        current_count = sum(o.booking_count for o in obs.filter(period_start__gte=this_week))
        previous_count = sum(o.booking_count for o in obs.filter(period_start__lt=this_week))

    trend = calculate_period_trend(previous_count, current_count)
    return {"count": current_count, "trend": trend}


def get_active_bench_metrics(
    *,
    unit: str | None = None,
    date_after: date | None = None,
    date_before: date | None = None,
) -> MetricResult:
    """Retrieve active bench population count or historical bucketed snapshots."""
    if unit:
        return _bucketed(
            ActiveLaboratoryObservation,
            unit,
            date_after=date_after,
            date_before=date_before,
            live_today=lambda _day: count_active_benches(),
            fill_missing_with_zero=False,
        )

    count = count_active_benches()
    if count == 0:
        latest = ActiveLaboratoryObservation.objects.order_by("-period_start").first()
        count = latest.active_laboratory_count if latest else 0

    return {"count": count, "trend": 0}


def get_active_user_metrics(
    *,
    unit: str | None = None,
    date_after: date | None = None,
    date_before: date | None = None,
) -> MetricResult:
    """Retrieve active user count or historical bucketed snapshots."""
    if unit:
        return _bucketed(
            ActiveUserObservation,
            unit,
            date_after=date_after,
            date_before=date_before,
            live_today=lambda _day: count_active_users(),
            fill_missing_with_zero=False,
        )

    count = count_active_users()
    if count == 0:
        latest = ActiveUserObservation.objects.order_by("-period_start").first()
        count = latest.active_user_count if latest else 0

    return {"count": count, "trend": 0}


def get_facility_visit_metrics(
    *,
    unit: str | None = None,
    date_after: date | None = None,
    date_before: date | None = None,
) -> MetricResult:
    """Retrieve distinct facility visitors: a rolling 7-day count with trend, or bucketed history.

    The summary counts distinct visitors (not visit events) in the last 7 days against the 7 days
    before, the same definition as the daily series (owner decision 2026-11-13).
    """
    if unit:
        return _bucketed(
            VisitorVolumeObservation,
            unit,
            date_after=date_after,
            date_before=date_before,
            live_today=lambda day: count_distinct_visitors(*_day_bounds(day)),
            fill_missing_with_zero=True,
        )

    now = timezone.now()
    this_week = now - timedelta(days=7)
    last_week = now - timedelta(days=14)

    current_count = count_distinct_visitors(this_week, now + timedelta(microseconds=1))
    previous_count = count_distinct_visitors(last_week, this_week)

    trend = calculate_period_trend(previous_count, current_count)
    return {"count": current_count, "trend": trend}


__all__ = [
    "count_active_benches",
    "count_active_users",
    "count_bookings_created",
    "count_distinct_visitors",
    "get_active_bench_metrics",
    "get_active_user_metrics",
    "get_booking_volume_metrics",
    "get_facility_visit_metrics",
]
