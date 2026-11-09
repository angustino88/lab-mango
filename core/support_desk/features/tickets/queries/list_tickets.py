"""Read query selector for ticket collections."""

from typing import Any

from django.db.models import Prefetch, QuerySet

from core.support_desk.features.tickets.application.policies import visible_tickets
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.ticket import SupportTicket

#: Large text columns the list projection never serializes.
_HEAVY_COLUMNS = ("description", "resolution_summary", "root_cause", "csat_comment")


def list_tickets(viewer: Any = None) -> QuerySet[SupportTicket]:
    """Base query for listing tickets with efficient joins and stable ordering.

    When ``viewer`` is given the result is restricted to tickets that user may see (agents: all;
    requesters: own / created / watched). Always pass the request user from API code.
    """
    qs = (
        SupportTicket.objects.select_related(
            "category",
            "priority",
            "status",
            "requester",
            "assignee",
            "team",
        )
        .prefetch_related(Prefetch("labels", queryset=SupportLabel.objects.order_by("name")))
        .defer(*_HEAVY_COLUMNS)
        .order_by("priority__rank", "created_at", "id")
    )
    if viewer is not None:
        qs = visible_tickets(qs, viewer)
    return qs
