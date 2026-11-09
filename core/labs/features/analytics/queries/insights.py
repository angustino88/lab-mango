"""Read-only KPI queries for dashboard summary, booked-vs-used, and equipment availability."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from core.labs.models import (
    Bench,
    BenchBooking,
    BookingStatus,
    Equipment,
    EquipmentStatus,
    EquipmentStatusRecord,
    LaboratoryVisitEvent,
    LabSessionLog,
)

from .calculations import calculate_official_working_hours, calculate_period_trend

# Bookings that consumed (or still hold) bench time. Cancelled and expired bookings do not.
_HOLDING_STATUSES = (BookingStatus.RESERVED, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED)

# Equipment statuses that mean the item is not available for use.
_UNAVAILABLE_STATUSES = frozenset({EquipmentStatus.MAINTENANCE, EquipmentStatus.BROKEN, EquipmentStatus.LOST})


def _previous_window(from_date_time: datetime, to_date_time: datetime) -> tuple[datetime, datetime]:
    """Return the equal-length window immediately before the requested one."""
    span = to_date_time - from_date_time
    return from_date_time - span, from_date_time


def _count_bookings(start: datetime, end: datetime) -> int:
    return BenchBooking.objects.filter(
        created__gte=start,
        created__lt=end,
    ).count()


def _count_visits(start: datetime, end: datetime) -> int:
    return LaboratoryVisitEvent.objects.filter(
        occurred_at__gte=start,
        occurred_at__lt=end,
    ).count()


def get_dashboard_summary(*, from_date_time: datetime, to_date_time: datetime) -> dict[str, Any]:
    """Return headline KPI cards with current value, previous period value, and trend.

    The previous period is the equal-length window immediately before the requested range.
    Active users and active benches are point-in-time counts, so they carry no trend.
    """
    prev_start, prev_end = _previous_window(from_date_time, to_date_time)

    current_bookings = _count_bookings(from_date_time, to_date_time)
    previous_bookings = _count_bookings(prev_start, prev_end)

    current_visits = _count_visits(from_date_time, to_date_time)
    previous_visits = _count_visits(prev_start, prev_end)

    active_benches = Bench.objects.filter(deleted_at__isnull=True).count()

    return {
        "generated_at": timezone.now(),
        "period_start": from_date_time,
        "period_end": to_date_time,
        "bookings": {
            "count": current_bookings,
            "previous_count": previous_bookings,
            "trend_percent": calculate_period_trend(previous_bookings, current_bookings),
        },
        "facility_visits": {
            "count": current_visits,
            "previous_count": previous_visits,
            "trend_percent": calculate_period_trend(previous_visits, current_visits),
        },
        "active_benches": {
            "count": active_benches,
        },
    }


def get_booked_vs_used(*, from_date_time: datetime, to_date_time: datetime) -> dict[str, Any]:
    """Compare reserved bench hours with recorded session hours over the requested range.

    Booked hours are reported per bench. Session logs carry no bench link, so used hours
    are reported as a single laboratory total; per-bench usage is not derivable from current data.
    Booked time is clipped to the requested range before summing.
    """
    bookings = BenchBooking.objects.filter(
        starts_at__lt=to_date_time,
        ends_at__gt=from_date_time,
        status__in=_HOLDING_STATUSES,
    ).select_related("bench")

    booked_hours: dict[str, float] = defaultdict(float)
    bench_names: dict[str, str] = {}
    for booking in bookings:
        clipped_start = max(booking.starts_at, from_date_time)
        clipped_end = min(booking.ends_at, to_date_time)
        hours = max(0.0, (clipped_end - clipped_start).total_seconds() / 3600.0)
        key = str(booking.bench_id)
        booked_hours[key] += hours
        bench_names[key] = booking.bench.name or booking.bench.sku or key

    benches = [
        {
            "bench_id": int(key),
            "bench_name": bench_names[key],
            "booked_hours": round(hours, 2),
        }
        for key, hours in booked_hours.items()
    ]
    benches.sort(key=lambda row: row["booked_hours"], reverse=True)

    used_seconds = (
        LabSessionLog.objects.filter(
            login_time__lt=to_date_time,
            logout_time__gt=from_date_time,
        ).aggregate(total=Sum("active_duration_seconds"))["total"]
        or 0.0
    )
    used_hours = used_seconds / 3600.0
    total_booked_hours = sum(booked_hours.values())
    working_hours = calculate_official_working_hours(from_date_time, to_date_time)

    return {
        "period_start": from_date_time,
        "period_end": to_date_time,
        "total_booked_hours": round(total_booked_hours, 2),
        "total_used_hours": round(used_hours, 2),
        "used_to_booked_ratio": round(min(used_hours / total_booked_hours, 1.0), 2) if total_booked_hours > 0 else None,
        "official_working_hours": round(working_hours, 2),
        "benches": benches,
    }


def get_equipment_availability(*, from_date_time: datetime, to_date_time: datetime) -> dict[str, Any]:
    """Estimate equipment availability from status history over the requested range.

    For each non-deleted equipment item, status is the last record at or before each change
    inside the window. Time in unavailable statuses counts against uptime. Items with no record
    before the window end are excluded because their status is unknown for that interval.
    """
    total_seconds = (to_date_time - from_date_time).total_seconds()
    if total_seconds <= 0:
        return {"period_start": from_date_time, "period_end": to_date_time, "equipment_count": 0,
                "average_uptime_percent": None, "items": []}

    records = (
        EquipmentStatusRecord.objects.filter(
            equipment__deleted_at__isnull=True,
            created__lt=to_date_time,
        )
        .order_by("equipment_id", "created", "id")
        .values("equipment_id", "status", "created")
    )

    by_equipment: dict[int, list[tuple[datetime, str]]] = defaultdict(list)
    for row in records:
        by_equipment[row["equipment_id"]].append((row["created"], row["status"]))

    names = dict(Equipment.objects.filter(pk__in=by_equipment.keys()).values_list("pk", "name"))

    items = []
    for equipment_id, history in by_equipment.items():
        # Status in force at window start is the last record created before the window.
        before = [(ts, st) for ts, st in history if ts <= from_date_time]
        inside = [(ts, st) for ts, st in history if from_date_time < ts < to_date_time]
        if not before and not inside:
            continue

        timeline: list[tuple[datetime, str]] = []
        if before:
            timeline.append((from_date_time, before[-1][1]))
        timeline.extend(inside)

        unavailable_seconds = 0.0
        outage_count = 0
        previous_unavailable = False
        for index, (start, status) in enumerate(timeline):
            end = timeline[index + 1][0] if index + 1 < len(timeline) else to_date_time
            is_unavailable = status in _UNAVAILABLE_STATUSES
            if is_unavailable:
                unavailable_seconds += (end - start).total_seconds()
                if not previous_unavailable:
                    outage_count += 1
            previous_unavailable = is_unavailable

        uptime = max(0.0, 1.0 - unavailable_seconds / total_seconds)
        items.append({
            "equipment_id": equipment_id,
            "equipment_name": names.get(equipment_id) or str(equipment_id),
            "uptime_percent": round(uptime * 100, 2),
            "unavailable_hours": round(unavailable_seconds / 3600.0, 2),
            "outage_count": outage_count,
            "current_status": timeline[-1][1],
        })

    items.sort(key=lambda row: row["uptime_percent"])
    average = round(sum(row["uptime_percent"] for row in items) / len(items), 2) if items else None
    return {
        "period_start": from_date_time,
        "period_end": to_date_time,
        "equipment_count": len(items),
        "average_uptime_percent": average,
        "items": items,
    }


__all__ = [
    "get_booked_vs_used",
    "get_dashboard_summary",
    "get_equipment_availability",
]
