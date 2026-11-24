"""Read selectors for personal, ticket, and team effort reports."""

from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, QuerySet, Sum

from core.support_desk.exceptions import PermissionDeniedError
from core.support_desk.features.tickets.application.policies import is_support_agent, visible_tickets
from core.support_desk.features.tickets.application.shared import get_ticket_for_actor
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.work_log import TicketWorkLog


def work_logs_for_report(actor: Any, filters: Mapping[str, Any]) -> QuerySet[TicketWorkLog]:
    scope = filters.get("scope", "mine")
    logs = TicketWorkLog.objects.all()
    if scope == "ticket":
        ticket = get_ticket_for_actor(filters["ticket_key"], actor)
        logs = logs.filter(ticket_id=ticket.pk)
    elif scope == "team":
        if not is_support_agent(actor):
            raise PermissionDeniedError("Team work logs are available to support staff.")
    else:
        visible = visible_tickets(SupportTicket.objects.all(), actor)
        logs = logs.filter(author=actor, ticket_id__in=visible.values("pk"))

    if author_id := filters.get("author_id"):
        logs = logs.filter(author_id=author_id)
    if team_id := filters.get("team_id"):
        logs = logs.filter(ticket__team_id=team_id)
    if started_after := filters.get("started_after"):
        logs = logs.filter(started_at__gte=started_after)
    if started_before := filters.get("started_before"):
        logs = logs.filter(started_at__lt=started_before)
    return logs


def summarize_work_logs(logs: QuerySet[TicketWorkLog], actor: Any) -> dict[str, int]:
    return logs.aggregate(
        total_minutes=Sum("time_spent_minutes", default=0),
        my_minutes=Sum("time_spent_minutes", filter=Q(author=actor), default=0),
        entry_count=Count("pk"),
        ticket_count=Count("ticket_id", distinct=True),
        contributor_count=Count("author_id", distinct=True),
    )


def list_work_log_contributors(logs: QuerySet[TicketWorkLog]) -> QuerySet:
    users = get_user_model()
    return (
        users.objects.filter(support_work_logs__in=logs.order_by().values("pk"))
        .only("id", "display_name", "name", "username", "first_name", "last_name")
        .annotate(
            total_minutes=Sum("support_work_logs__time_spent_minutes"),
            entry_count=Count("support_work_logs"),
            ticket_count=Count("support_work_logs__ticket", distinct=True),
        )
        .order_by("-total_minutes", "pk")
    )
