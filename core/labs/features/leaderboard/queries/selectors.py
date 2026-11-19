"""Read-only selectors for computing leaderboard rankings and operational analytics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from core.labs.features.equipment.public import get_equipment_status_summary
from core.labs.models import (
    Bench,
    BenchBooking,
    BookingApprovalStatus,
    BookingStatus,
    LabSessionLog,
)

from ..exceptions import ResourceNotFoundError
from ..helpers import (
    calculate_late_rate_from_tuples,
    clamp,
    count_weekdays,
)


# Bookings a person was expected to attend: approved, not cancelled, already started (the KPI window
# never counts future bookings). Expired bookings stay in: they are the no-shows.
def _attendable_bookings(start_date: datetime, end_date: datetime):
    return BenchBooking.objects.filter(
        starts_at__gte=start_date,
        starts_at__lte=min(end_date, timezone.now()),
        approval_status=BookingApprovalStatus.APPROVED,
    ).exclude(status=BookingStatus.CANCELLED)


def _login_key(name: str | None) -> str:
    """Login name as the session log resolves it: case ignored, Windows ``DOMAIN\\`` prefix dropped."""
    return (name or "").strip().rsplit("\\", 1)[-1].strip().lower()


def _seconds(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds())


def _active_seconds(row: dict[str, Any]) -> float:
    """Active time the agent reported, else the whole session (rows stored before it was reported)."""
    wall = _seconds(row["login_time"], row["logout_time"])
    active = row.get("active_duration_seconds")
    return min(wall, max(0.0, float(active))) if active is not None else wall


def _ratio(part: float, whole: float) -> float | None:
    """Rounded ``part / whole`` in [0, 1], or None when there is nothing to measure against."""
    return round(clamp(part / whole), 2) if whole > 0 else None


def _booking_usage(bookings: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    """Per booking: session seconds inside the slot, session seconds in total, whether anyone attended."""
    usage: dict[int, dict[str, float]] = {
        b["id"]: {"in_slot": 0.0, "total": 0.0, "attended": 0.0} for b in bookings
    }
    slots = {b["id"]: (b["starts_at"], b["ends_at"]) for b in bookings}
    linked = LabSessionLog.objects.filter(
        booking_id__in=list(slots), login_time__isnull=False, logout_time__isnull=False
    ).values("booking_id", "login_time", "logout_time")
    for row in linked:
        slot_start, slot_end = slots[row["booking_id"]]
        entry = usage[row["booking_id"]]
        entry["attended"] = 1.0
        entry["total"] += _seconds(row["login_time"], row["logout_time"])
        entry["in_slot"] += _seconds(max(row["login_time"], slot_start), min(row["logout_time"], slot_end))
    return usage


def _booking_kpis(bookings: list[dict[str, Any]], usage: dict[int, dict[str, float]]) -> dict[str, Any]:
    """Attendance, use of booked time and slot adherence over a set of bookings."""
    total = len(bookings)
    attended = sum(1 for b in bookings if usage[b["id"]]["attended"])
    booked = sum(_seconds(b["starts_at"], b["ends_at"]) for b in bookings)
    # Time used of each booking, capped at its own length so one long session cannot hide a no-show.
    used = sum(min(usage[b["id"]]["in_slot"], _seconds(b["starts_at"], b["ends_at"])) for b in bookings)
    in_slot = sum(usage[b["id"]]["in_slot"] for b in bookings)
    session_time = sum(usage[b["id"]]["total"] for b in bookings)
    return {
        "total_bookings": total,
        "no_show_bookings": total - attended,
        "booking_compliance": _ratio(attended, total),
        "booking_utilization": _ratio(used, booked),
        "slot_adherence": _ratio(in_slot, session_time),
        "booked_minutes": booked / 60,
    }


def _top_projects(bookings: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for b in bookings:
        if b["project__project_name"]:
            counts[b["project__project_name"]] += 1
    return [name for name, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:3]]


def compute_leaderboard_persona(
    start_date: datetime,
    end_date: datetime,
    *,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """KPIs and points per user for the date window (KPI definitions: docs/architecture.md section 5).

    Sessions count for the app user the session log resolved; rows stored before that link existed
    fall back to the login name. Bookings count for the person they are for (requester, else creator).
    ``user_id`` narrows the read to one person (the assessment); the figures are the same as in the
    full ranking.
    """
    session_qs = LabSessionLog.objects.filter(
        login_time__gte=start_date,
        login_time__lte=end_date,
        login_time__isnull=False,
        logout_time__isnull=False,
    )
    booking_qs = _attendable_bookings(start_date, end_date)
    User = get_user_model()
    if user_id is not None:
        username = User.objects.filter(pk=user_id).values_list("username", flat=True).first() or ""
        # Unlinked rows are narrowed by name here and matched exactly below.
        unlinked = Q(user_id__isnull=True, remote_user__icontains=username) if username else Q(pk__in=[])
        session_qs = session_qs.filter(Q(user_id=user_id) | unlinked)
        booking_qs = booking_qs.filter(Q(requester_id=user_id) | Q(requester_id__isnull=True, creator_id=user_id))
    sessions = list(
        session_qs.values(
            "user_id",
            "remote_user",
            "login_time",
            "logout_time",
            "active_duration_seconds",
            "computing_equipment_id",
            "booking_id",
        )
    )
    bookings = list(
        booking_qs.values("id", "requester_id", "creator_id", "starts_at", "ends_at", "project__project_name")
    )

    user_ids = {row["user_id"] for row in sessions if row["user_id"]}
    user_ids |= {b["requester_id"] or b["creator_id"] for b in bookings if b["requester_id"] or b["creator_id"]}
    login_names = {_login_key(row["remote_user"]) for row in sessions if not row["user_id"]} - {""}
    users = {
        user.pk: user
        for user in User.objects.annotate(login_key=Lower("username"))
        .filter(is_active=True)
        .filter(Q(pk__in=user_ids) | Q(login_key__in=login_names))
        .filter(**({"pk": user_id} if user_id is not None else {}))
        .only("id", "username", "display_name", "first_name", "last_name", "avatar")
    }
    by_login: dict[str, list[int]] = defaultdict(list)
    for user in users.values():
        by_login[user.username.lower()].append(user.pk)

    sessions_by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sessions:
        owner = row["user_id"]
        if owner is None:
            matches = by_login.get(_login_key(row["remote_user"]), [])
            owner = matches[0] if len(matches) == 1 else None  # never attribute to a guessed person
        if owner in users:
            sessions_by_user[owner].append(row)

    bookings_by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for b in bookings:
        owner = b["requester_id"] or b["creator_id"]
        if owner in users:
            bookings_by_user[owner].append(b)
    usage = _booking_usage(bookings)

    num_weekdays = max(1, count_weekdays(start_date, end_date))
    result: list[dict[str, Any]] = []

    for pk, user in users.items():
        rows = sessions_by_user.get(pk, [])
        user_bookings = bookings_by_user.get(pk, [])
        if not rows and not user_bookings:
            continue
        total_sessions = len(rows)
        wall_seconds = [_seconds(r["login_time"], r["logout_time"]) for r in rows]
        total_dur_min = sum(wall_seconds) / 60
        active_min = sum(_active_seconds(r) for r in rows) / 60
        late_rate = calculate_late_rate_from_tuples([(r["login_time"], r["logout_time"]) for r in rows])

        # RFO/RFH: unchanged detection (sessions against two per weekday).
        wfo_rate = round(min(1.0, total_sessions / (num_weekdays * 2)), 2)
        wfh_rate = round(max(0.0, 1.0 - wfo_rate), 2)
        usage_efficiency = round(clamp(active_min / (num_weekdays * 480)), 2)
        booking = _booking_kpis(user_bookings, usage)

        # Points reflect how much the lab is used (logins and active hours) and how well bookings are kept.
        points = int(
            total_sessions * 10
            + (active_min / 60) * 10
            + usage_efficiency * 100
            + (booking["booking_compliance"] or 0) * 50
            + (booking["booking_utilization"] or 0) * 50
            + (booking["slot_adherence"] or 0) * 20
            - late_rate * 30
        )

        display_name = getattr(user, "display_name", None) or user.get_full_name() or user.username
        result.append({
            "id": pk,
            "username": user.username,
            "display_name": display_name,
            "avatar": getattr(user, "avatar_url", None),
            "points": max(0, points),
            "wfo_rate": wfo_rate,
            "wfh_rate": wfh_rate,
            "late_rate": late_rate,
            "usage_efficiency": usage_efficiency,
            "active_rate": _ratio(active_min, total_dur_min),
            "ad_hoc_rate": _ratio(sum(1 for r in rows if not r["booking_id"]), total_sessions),
            "booking_compliance": booking["booking_compliance"],
            "booking_utilization": booking["booking_utilization"],
            "slot_adherence": booking["slot_adherence"],
            "no_show_bookings": booking["no_show_bookings"],
            "last_remote": max((r["login_time"] for r in rows), default=None),
            "labs_accessed": len({r["computing_equipment_id"] for r in rows if r["computing_equipment_id"]}),
            "total_bookings": booking["total_bookings"],
            "total_sessions": total_sessions,
            "total_usage_minutes": round(total_dur_min, 2),
            "active_usage_minutes": round(active_min, 2),
            "avg_session_minutes": round(total_dur_min / total_sessions, 2) if total_sessions else 0.0,
            "longest_session_minutes": round(max(wall_seconds, default=0.0) / 60, 2),
            "top_projects": _top_projects(user_bookings),
        })

    result.sort(key=lambda x: x["points"], reverse=True)
    return result


def compute_leaderboard_lab(
    start_date: datetime,
    end_date: datetime,
    *,
    bench_id: int | None = None,
) -> list[dict[str, Any]]:
    """KPIs and points per bench for the date window.

    Sessions count for the bench the computer stood on at login (``LabSessionLog.bench``), so moving a
    computer later does not move its history. Four queries in total, whatever the number of benches.
    """
    scope = {"bench_id": bench_id} if bench_id is not None else {}
    only_bench = {"pk": bench_id} if bench_id is not None else {}
    benches = list(Bench.objects.filter(deleted_at__isnull=True, **only_bench).values("id", "name"))
    sessions_by_bench: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in LabSessionLog.objects.filter(
        bench_id__isnull=False,
        login_time__gte=start_date,
        login_time__lte=end_date,
        login_time__isnull=False,
        logout_time__isnull=False,
        **scope,
    ).values("bench_id", "user_id", "remote_user", "login_time", "logout_time", "active_duration_seconds"):
        sessions_by_bench[row["bench_id"]].append(row)

    bookings = list(
        _attendable_bookings(start_date, end_date).filter(**scope).values(
            "id", "bench_id", "starts_at", "ends_at", "project__project_name"
        )
    )
    bookings_by_bench: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for b in bookings:
        bookings_by_bench[b["bench_id"]].append(b)
    usage = _booking_usage(bookings)

    capacity_min = max(1, count_weekdays(start_date, end_date)) * 480
    result = []
    for bench in benches:
        rows = sessions_by_bench.get(bench["id"], [])
        bench_bookings = bookings_by_bench.get(bench["id"], [])
        active_min = sum(_active_seconds(r) for r in rows) / 60
        users = {r["user_id"] or _login_key(r["remote_user"]) for r in rows} - {""}
        booking = _booking_kpis(bench_bookings, usage)
        utilization_rate = round(clamp(active_min / capacity_min), 2)
        points = int(
            len(rows) * 20
            + (active_min / 60) * 10
            + len(users) * 15
            + utilization_rate * 100
            + (booking["booking_compliance"] or 0) * 50
        )

        result.append({
            "id": bench["id"],
            "name": bench["name"],
            "points": max(0, points),
            "total_sessions": len(rows),
            "active_users": len(users),
            "last_remote": max((r["login_time"] for r in rows), default=None),
            "total_usage_minutes": round(active_min, 2),
            "utilization_rate": utilization_rate,
            "booking_fill": round(clamp(booking["booked_minutes"] / capacity_min), 2),
            "total_bookings": booking["total_bookings"],
            "no_show_bookings": booking["no_show_bookings"],
            "booking_compliance": booking["booking_compliance"],
            "booking_utilization": booking["booking_utilization"],
            "downtime_minutes": 0.0,
            "top_projects": _top_projects(bench_bookings),
        })

    result.sort(key=lambda x: x["points"], reverse=True)
    return result


def get_lab_profile(pk: int, start_date: datetime, end_date: datetime) -> dict[str, Any]:
    """Retrieve profile and usage statistics for a specific bench."""
    bench = Bench.objects.filter(pk=pk, deleted_at__isnull=True).first()
    if not bench:
        raise ResourceNotFoundError(f"Bench {pk} not found")

    sessions = LabSessionLog.objects.filter(
        computing_equipment__bench_assignments__bench=bench,
        computing_equipment__bench_assignments__unassigned_at__isnull=True,
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
