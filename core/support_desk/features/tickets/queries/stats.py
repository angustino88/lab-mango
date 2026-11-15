"""Queue dashboard aggregates for support agents."""

from datetime import timedelta
from typing import Any

from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from core.support_desk.contracts import SystemState
from core.support_desk.models.ticket import SupportTicket


def _minutes(value: timedelta | None) -> float | None:
    return round(value.total_seconds() / 60, 1) if value is not None else None


def get_queue_stats(*, viewer: Any, days: int = 30) -> dict[str, Any]:
    """Operational snapshot of the desk (open workload, SLA health, throughput, CSAT).

    The caller is responsible for restricting this to support agents.
    """
    now = timezone.now()
    since = now - timedelta(days=days)
    open_qs = SupportTicket.objects.exclude(status__system_state=SystemState.DONE.value)

    by_state = {
        row["status__system_state"]: row["n"]
        for row in SupportTicket.objects.values("status__system_state").annotate(n=Count("id"))
    }
    by_priority = list(
        open_qs.values("priority_id", "priority__name", "priority__rank")
        .annotate(count=Count("id"))
        .order_by("priority__rank")
    )
    by_team = list(
        open_qs.values("team_id", "team__name").annotate(count=Count("id")).order_by("-count", "team__name")
    )
    by_assignee = list(
        open_qs.filter(assignee__isnull=False)
        .values("assignee_id", "assignee__username", "assignee__display_name", "assignee__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:20]
    )
    by_type = {
        row["ticket_type"]: row["count"] for row in open_qs.values("ticket_type").annotate(count=Count("id"))
    }

    sla = open_qs.aggregate(
        response_breached=Count("id", filter=Q(response_breached_at__isnull=False)),
        resolution_breached=Count("id", filter=Q(resolution_breached_at__isnull=False)),
        overdue_resolution=Count("id", filter=Q(resolution_due_at__lt=now, sla_paused_at__isnull=True)),
        paused=Count("id", filter=Q(sla_paused_at__isnull=False)),
    )

    recent = SupportTicket.objects.filter(created_at__gte=since).aggregate(
        created=Count("id"),
        avg_first_response=Avg(F("first_response_at") - F("created_at"), filter=Q(first_response_at__isnull=False)),
    )
    resolved = SupportTicket.objects.filter(resolved_at__gte=since).aggregate(
        resolved=Count("id"),
        avg_resolution=Avg(F("resolved_at") - F("created_at")),
        reopened=Count("id", filter=Q(reopen_count__gt=0)),
        csat_avg=Avg("csat_score"),
        csat_responses=Count("id", filter=Q(csat_score__isnull=False)),
    )

    return {
        "window_days": days,
        "open_total": open_qs.count(),
        "unassigned": open_qs.filter(assignee__isnull=True).count(),
        "mine_open": open_qs.filter(assignee=viewer).count(),
        "by_state": by_state,
        "by_type": by_type,
        "by_priority": [
            {"priority_id": r["priority_id"], "name": r["priority__name"], "rank": r["priority__rank"], "count": r["count"]}
            for r in by_priority
        ],
        "by_team": [{"team_id": r["team_id"], "name": r["team__name"] or "", "count": r["count"]} for r in by_team],
        "by_assignee": [
            {
                "user_id": r["assignee_id"],
                # REL-3 user name: display name, then name, then username.
                "username": r["assignee__display_name"] or r["assignee__name"] or r["assignee__username"],
                "count": r["count"],
            }
            for r in by_assignee
        ],
        "sla": sla,
        "created": recent["created"],
        "resolved": resolved["resolved"],
        "reopened": resolved["reopened"],
        "avg_first_response_minutes": _minutes(recent["avg_first_response"]),
        "avg_resolution_minutes": _minutes(resolved["avg_resolution"]),
        "csat_average": round(resolved["csat_avg"], 2) if resolved["csat_avg"] is not None else None,
        "csat_responses": resolved["csat_responses"],
    }
