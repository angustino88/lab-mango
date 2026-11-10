"""Read-only queries for laboratory utilization, equipment efficiency, and consumption."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from django.db.models import Count, Q

from core.labs.features.equipment.public import get_equipment_status_summary
from core.labs.models import (
    Bench,
    BenchBooking,
    BenchGroup,
    LabSessionLog,
    ProjectUsageObservation,
)

from .calculations import (
    SLOT_LABELS,
    calculate_official_working_hours,
    calculate_timeslot_distribution,
)


def get_bench_group_distribution() -> list[dict[str, Any]]:
    """Return distribution of benches grouped by bench groups in a single query."""
    groups = BenchGroup.objects.annotate(
        total_benches=Count("benches", filter=Q(benches__deleted_at__isnull=True))
    ).order_by("name", "pk")
    results = [
        {
            "id": bg.pk,
            "name": bg.name,
            "bench_group_name": bg.name,
            "total_benches": bg.total_benches,
            "active_benches": bg.total_benches,
            "entries": bg.total_benches,
        }
        for bg in groups
    ]

    if not results:
        total_benches = Bench.objects.filter(deleted_at__isnull=True).count()
        if total_benches > 0:
            results.append({
                "id": 1,
                "name": "Default Group",
                "bench_group_name": "Default Group",
                "total_benches": total_benches,
                "active_benches": total_benches,
                "entries": total_benches,
            })
    return results


def get_equipment_status_distribution() -> list[dict[str, Any]]:
    """Number of non-deleted equipment items per computed display status (equipment owns the rule)."""
    summary = get_equipment_status_summary()
    return [
        {"status": row["status"]["value"], "count": row["resource_count"], "entries": row["resource_count"]}
        for row in summary["statuses"]
    ]


def get_bench_efficiency_rankings(
    *,
    from_date_time: datetime,
    to_date_time: datetime,
    sort_order: str = "desc",
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Calculate asset efficiency over official laboratory operating hours."""
    working_hours = calculate_official_working_hours(from_date_time, to_date_time)
    logs = LabSessionLog.objects.filter(
        login_time__lt=to_date_time,
        logout_time__gt=from_date_time,
    ).select_related("computing_equipment")

    durations: dict[tuple[str, str], float] = defaultdict(float)
    bookings: dict[tuple[str, str], set[str]] = defaultdict(set)

    for log in logs:
        eq_name = getattr(log.computing_equipment, "name", None) or log.host_name or "N/A"
        bench_name = "Default Lab"
        key = (bench_name, eq_name)
        if log.booking_code:
            bookings[key].add(log.booking_code)
        duration_minutes = log.duration_minutes or 0.0
        durations[key] += duration_minutes / 60.0

    data = []
    for (bench_name, eq_name), hours in durations.items():
        efficiency = round(min(hours / working_hours, 1.0), 2) if working_hours > 0 else 0.0
        data.append({
            "name": bench_name,
            "lab_name": bench_name,
            "computer_name": eq_name,
            "efficiency": efficiency,
            "duration": round(hours, 2),
            "booking": len(bookings.get((bench_name, eq_name), set())),
        })

    data.sort(key=lambda x: x["efficiency"], reverse=(sort_order == "desc"))
    if top_n is not None and top_n > 0:
        data = data[:top_n]
    return data


def get_project_utilization(
    *,
    from_date_time: datetime,
    to_date_time: datetime,
    sort_order: str = "desc",
    top_n: int | None = 5,
) -> list[dict[str, Any]]:
    """Aggregate utilization duration by project."""
    usage_by_project: dict[str, float] = defaultdict(float)

    observations = ProjectUsageObservation.objects.filter(
        period_start__lt=to_date_time,
        period_end__gt=from_date_time,
    ).select_related("project")

    for obs in observations:
        name = obs.project.name if obs.project else obs.project_identifier or "Unassigned"
        usage_by_project[name] += obs.booked_seconds / 3600.0

    bookings = BenchBooking.objects.filter(
        starts_at__lt=to_date_time,
        ends_at__gt=from_date_time,
    ).select_related("project")

    for b in bookings:
        proj_name = b.project.name if b.project else "Unassigned"
        duration_hours = (b.ends_at - b.starts_at).total_seconds() / 3600.0
        usage_by_project[proj_name] += duration_hours

    data = [{"project_name": name, "usage": round(usage, 2)} for name, usage in usage_by_project.items()]
    data.sort(key=lambda x: x["usage"], reverse=(sort_order == "desc"))
    if top_n is not None and top_n > 0:
        data = data[:top_n]
    return data


def get_user_utilization(
    *,
    from_date_time: datetime,
    to_date_time: datetime,
    sort_order: str = "desc",
    top_n: int | None = 5,
) -> list[dict[str, Any]]:
    """Aggregate total logged usage duration by user."""
    logs = LabSessionLog.objects.filter(
        login_time__lt=to_date_time,
        logout_time__gt=from_date_time,
    )

    usage_by_user: dict[str, float] = defaultdict(float)
    display_names: dict[str, str] = {}

    for log in logs:
        user = log.remote_user or "anonymous"
        display_names[user] = log.remote_user_display_name or user
        dur = (log.duration_minutes or 0.0) / 60.0
        usage_by_user[user] += dur

    data = [
        {
            "remote_user": user,
            "usage": round(duration, 2),
            "remote_user_displayname": display_names.get(user, user),
        }
        for user, duration in usage_by_user.items()
    ]
    data.sort(key=lambda x: x["usage"], reverse=(sort_order == "desc"))
    if top_n is not None and top_n > 0:
        data = data[:top_n]
    return data


def get_user_booking_compliance(
    *,
    from_date_time: datetime,
    to_date_time: datetime,
    sort_order: str = "desc",
    top_n: int | None = 5,
) -> list[dict[str, Any]]:
    """Compare user active session usage to reserved booking duration."""
    bookings = BenchBooking.objects.filter(
        starts_at__lt=to_date_time,
        ends_at__gt=from_date_time,
    ).select_related("creator")

    booked_hours: dict[str, float] = defaultdict(float)
    for b in bookings:
        username = b.creator.username if b.creator else "anonymous"
        hours = (b.ends_at - b.starts_at).total_seconds() / 3600.0
        booked_hours[username] += max(0.0, hours)

    logs = LabSessionLog.objects.filter(
        login_time__lt=to_date_time,
        logout_time__gt=from_date_time,
    )

    used_hours: dict[str, float] = defaultdict(float)
    display_names: dict[str, str] = {}
    for log in logs:
        user = log.remote_user or "anonymous"
        display_names[user] = log.remote_user_display_name or user
        used_hours[user] += (log.duration_minutes or 0.0) / 60.0

    all_users = set(booked_hours.keys()) | set(used_hours.keys())
    data = []
    for user in all_users:
        booked = booked_hours.get(user, 0.0)
        used = used_hours.get(user, 0.0)
        eff = round(min(used / booked, 1.0), 2) if booked > 0 else 0.0
        data.append({
            "remote_user": user,
            "efficiency": eff,
            "remote_user_displayname": display_names.get(user, user),
        })

    data.sort(key=lambda x: x["efficiency"], reverse=(sort_order == "desc"))
    if top_n is not None and top_n > 0:
        data = data[:top_n]
    return data


def get_timeframe_utilization(
    *,
    from_date_time: datetime,
    to_date_time: datetime,
) -> list[dict[str, Any]]:
    """Partition elapsed session duration across standard daily timeslot buckets."""
    usage = [0.0] * 12
    logs = LabSessionLog.objects.filter(
        login_time__lt=to_date_time,
        logout_time__gt=from_date_time,
    ).values("login_time", "logout_time")

    for log in logs:
        login = log["login_time"]
        logout = log["logout_time"]
        if not login or not logout:
            continue
        slots = calculate_timeslot_distribution(login, logout)
        for i, hours in enumerate(slots):
            usage[i] += hours

    return [{"timeslot": SLOT_LABELS[i], "usage": round(usage[i], 2)} for i in range(12)]


__all__ = [
    "get_bench_efficiency_rankings",
    "get_bench_group_distribution",
    "get_equipment_status_distribution",
    "get_project_utilization",
    "get_timeframe_utilization",
    "get_user_booking_compliance",
    "get_user_utilization",
]
