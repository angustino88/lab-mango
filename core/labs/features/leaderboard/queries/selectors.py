"""Read-only selectors for computing leaderboard rankings and operational analytics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count, DurationField, ExpressionWrapper, F, Max, Sum

from core.labs.features.equipment.public import get_equipment_status_summary
from core.labs.models import (
    Bench,
    BenchBooking,
    LabSessionLog,
)

from ..exceptions import ResourceNotFoundError
from ..helpers import (
    calculate_late_rate_from_tuples,
    clamp,
    count_weekdays,
)


def compute_leaderboard_persona(
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    """Compute persona ranking and scoring across users for the date window."""
    sessions_qs = LabSessionLog.objects.filter(
        login_time__gte=start_date,
        login_time__lte=end_date,
        login_time__isnull=False,
        logout_time__isnull=False,
    )

    # Aggregate bookings by user
    bookings_qs = BenchBooking.objects.filter(
        starts_at__gte=start_date,
        ends_at__lte=end_date,
    ).select_related("creator", "project")

    active_usernames = set(
        sessions_qs.exclude(remote_user="").values_list("remote_user", flat=True).distinct()
    ) | set(
        bookings_qs.exclude(creator__username="").values_list("creator__username", flat=True).distinct()
    )

    User = get_user_model()
    users = {
        u.username: u
        for u in User.objects.filter(is_active=True, username__in=active_usernames).only(
            "id", "username", "display_name", "first_name", "last_name", "avatar"
        )
    }

    agg = sessions_qs.values("remote_user").annotate(
        total_sessions=Count("id"),
        total_duration=Sum(
            ExpressionWrapper(F("logout_time") - F("login_time"), output_field=DurationField())
        ),
        longest_session=Max(
            ExpressionWrapper(F("logout_time") - F("login_time"), output_field=DurationField())
        ),
        last_remote=Max("login_time"),
        labs_accessed=Count("computing_equipment", distinct=True),
    )
    user_session_stats = {row["remote_user"]: row for row in agg if row["remote_user"]}

    # Group session intervals for late rate
    user_session_tuples: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for log in sessions_qs.values("remote_user", "login_time", "logout_time"):
        u = log["remote_user"]
        if u and log["login_time"] and log["logout_time"]:
            user_session_tuples[u].append((log["login_time"], log["logout_time"]))

    user_late_rates = {
        u: calculate_late_rate_from_tuples(tuples)
        for u, tuples in user_session_tuples.items()
    }

    user_booking_counts: dict[str, int] = defaultdict(int)
    user_project_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for b in bookings_qs:
        if b.creator and b.creator.username:
            un = b.creator.username
            user_booking_counts[un] += 1
            if b.project and b.project.name:
                user_project_counts[un][b.project.name] += 1

    user_top_projects = {
        un: [proj for proj, _ in sorted(proj_map.items(), key=lambda x: x[1], reverse=True)[:3]]
        for un, proj_map in user_project_counts.items()
    }

    num_weekdays = max(1, count_weekdays(start_date, end_date))
    result: list[dict[str, Any]] = []

    for un, user in users.items():
        s = user_session_stats.get(un, {})
        total_sessions = s.get("total_sessions", 0)
        tot_dur = s.get("total_duration")
        total_dur_min = tot_dur.total_seconds() / 60 if tot_dur else 0.0

        longest = s.get("longest_session")
        longest_session_minutes = longest.total_seconds() / 60 if longest else 0.0
        avg_session_minutes = round(total_dur_min / total_sessions, 2) if total_sessions > 0 else 0.0

        total_bookings = user_booking_counts.get(un, 0)
        late_rate = user_late_rates.get(un, 0.0)

        # Work from office vs home rates
        wfo_rate = round(min(1.0, total_sessions / (num_weekdays * 2)), 2)
        wfh_rate = round(max(0.0, 1.0 - wfo_rate), 2)
        usage_efficiency = round(clamp(total_dur_min / (num_weekdays * 480)), 2)
        booking_compliance = round(clamp(total_sessions / total_bookings if total_bookings > 0 else 1.0), 2)

        # Overall points calculation
        points = int(
            (total_sessions * 10)
            + (total_dur_min * 0.1)
            + (usage_efficiency * 100)
            + (booking_compliance * 50)
            - (late_rate * 30)
        )
        points = max(0, points)

        display_name = getattr(user, "display_name", None) or getattr(user, "get_full_name", lambda: "")() or un
        avatar = getattr(user, "avatar_url", None)

        result.append({
            "id": user.pk,
            "username": un,
            "display_name": display_name,
            "avatar": avatar,
            "points": points,
            "wfo_rate": wfo_rate,
            "wfh_rate": wfh_rate,
            "late_rate": late_rate,
            "usage_efficiency": usage_efficiency,
            "booking_compliance": booking_compliance,
            "last_remote": s.get("last_remote"),
            "labs_accessed": s.get("labs_accessed", 0),
            "total_bookings": total_bookings,
            "total_sessions": total_sessions,
            "total_usage_minutes": round(total_dur_min, 2),
            "avg_session_minutes": avg_session_minutes,
            "longest_session_minutes": round(longest_session_minutes, 2),
            "top_projects": user_top_projects.get(un, []),
        })

    result.sort(key=lambda x: x["points"], reverse=True)
    return result


def compute_leaderboard_lab(
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    """Compute laboratory utilization rankings."""
    benches = Bench.objects.filter(deleted_at__isnull=True)
    result = []
    for bench in benches:
        sessions = LabSessionLog.objects.filter(
            computing_equipment__equipmentassignment__bench=bench,
            computing_equipment__equipmentassignment__unassigned_at__isnull=True,
            login_time__gte=start_date,
            login_time__lte=end_date,
        )
        total_sessions = sessions.count()
        active_users = sessions.values("remote_user").distinct().count()
        last_remote = sessions.aggregate(Max("login_time"))["login_time__max"]
        points = total_sessions * 20 + active_users * 15

        result.append({
            "id": bench.pk,
            "name": bench.name,
            "points": points,
            "total_sessions": total_sessions,
            "active_users": active_users,
            "last_remote": last_remote,
            "downtime_minutes": 0.0,
            "top_projects": [],
        })

    result.sort(key=lambda x: x["points"], reverse=True)
    return result


def get_lab_profile(pk: int, start_date: datetime, end_date: datetime) -> dict[str, Any]:
    """Retrieve profile and usage statistics for a specific bench."""
    bench = Bench.objects.filter(pk=pk, deleted_at__isnull=True).first()
    if not bench:
        raise ResourceNotFoundError(f"Bench {pk} not found")

    sessions = LabSessionLog.objects.filter(
        computing_equipment__equipmentassignment__bench=bench,
        computing_equipment__equipmentassignment__unassigned_at__isnull=True,
        login_time__gte=start_date,
        login_time__lte=end_date,
    )
    total_sessions = sessions.count()
    active_users = sessions.values("remote_user").distinct().count()

    return {
        "id": bench.pk,
        "name": bench.name,
        "sku": bench.sku,
        "total_sessions": total_sessions,
        "active_users": active_users,
        "top_projects": [],
    }


def get_lab_weekly_usage(pk: int) -> list[dict[str, Any]]:
    """Generate weekly usage heatmap entries for a bench."""
    bench = Bench.objects.filter(pk=pk, deleted_at__isnull=True).first()
    if not bench:
        raise ResourceNotFoundError(f"Bench {pk} not found")

    # Generate standard 7 days x 24 hours heatmap slots
    heatmap = []
    for day in range(7):
        for hour in range(24):
            heatmap.append({"day": day, "hour": hour, "usage": 0.0})
    return heatmap


def get_user_profile(pk: int, start_date: datetime, end_date: datetime) -> dict[str, Any]:
    """Retrieve personal leaderboard profile for a specific user."""
    User = get_user_model()
    user = User.objects.filter(pk=pk, is_active=True).first()
    if not user:
        raise ResourceNotFoundError(f"User {pk} not found")

    sessions = LabSessionLog.objects.filter(
        remote_user=user.username,
        login_time__gte=start_date,
        login_time__lte=end_date,
    )
    total_sessions = sessions.count()

    return {
        "id": user.pk,
        "username": user.username,
        "display_name": getattr(user, "display_name", "") or user.username,
        "total_sessions": total_sessions,
        "points": total_sessions * 10,
        "top_projects": [],
    }


def get_user_weekly_usage(pk: int) -> list[dict[str, Any]]:
    """Generate weekly usage heatmap entries for an individual user."""
    User = get_user_model()
    user = User.objects.filter(pk=pk, is_active=True).first()
    if not user:
        raise ResourceNotFoundError(f"User {pk} not found")

    heatmap = []
    for day in range(7):
        for hour in range(24):
            heatmap.append({"day": day, "hour": hour, "usage": 0.0})
    return heatmap


def get_dashboard_summary() -> dict[str, Any]:
    """Return dashboard summary with total equipment and current status counts.

    Each non-deleted unit is counted once, under its latest recorded status (equipment owns
    that rule). ``total`` is the number of non-deleted units, including units with no status yet.
    """
    summary = get_equipment_status_summary()
    status_counts = {row["status"]["value"]: row["resource_count"] for row in summary["statuses"]}
    return {"total": summary["total_count"], "status": status_counts}


def get_dashboard_labs() -> list[dict[str, Any]]:
    """Return summary list of laboratory benches for dashboard view."""
    benches = Bench.objects.filter(deleted_at__isnull=True)
    return [{"id": b.pk, "name": b.name, "sku": b.sku, "status": "available"} for b in benches]


__all__ = [
    "compute_leaderboard_lab",
    "compute_leaderboard_persona",
    "get_dashboard_labs",
    "get_dashboard_summary",
    "get_lab_profile",
    "get_lab_weekly_usage",
    "get_user_profile",
    "get_user_weekly_usage",
]
