"""Read query selector for ticket detail."""

from typing import Any

from django.db.models import Prefetch

from core.support_desk.features.tickets.application.policies import can_view_ticket
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.comment import TicketComment
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.ticket_link import TicketLink
from core.support_desk.models.watcher import TicketWatcher


def get_ticket_by_key(ticket_key: str, *, viewer: Any = None) -> SupportTicket | None:
    """Fetch complete ticket projection by its public key.

    If ``viewer`` is supplied and may not see the ticket, ``None`` is returned (indistinguishable from "missing").
    """
    ticket = (
        SupportTicket.objects.select_related(
            "category",
            "priority",
            "status",
            "requester",
            "created_by",
            "assignee",
            "resolved_by",
            "team",
            "parent",
        )
        .prefetch_related(
            Prefetch("labels", queryset=SupportLabel.objects.order_by("name")),
            Prefetch("watchers", queryset=TicketWatcher.objects.select_related("user").order_by("created_at")),
            Prefetch("children", queryset=SupportTicket.objects.select_related("status", "priority").order_by("number")),
            Prefetch(
                "outgoing_links",
                queryset=TicketLink.objects.select_related("target", "target__status").order_by("created_at"),
            ),
            Prefetch(
                "incoming_links",
                queryset=TicketLink.objects.select_related("source", "source__status").order_by("created_at"),
            ),
            Prefetch(
                "resource_links",
                queryset=TicketResourceLink.objects.select_related("linked_by", "unlinked_by").order_by("-linked_at"),
            ),
            Prefetch(
                "comments",
                queryset=TicketComment.objects.select_related("author").filter(deleted_at__isnull=True).order_by("created_at"),
            ),
            Prefetch(
                "attachments",
                queryset=TicketAttachment.objects.select_related("uploaded_by").filter(deleted_at__isnull=True).order_by("created_at"),
            ),
            Prefetch(
                "activities",
                queryset=TicketActivity.objects.select_related("actor").order_by("occurred_at"),
            ),
        )
        .filter(key=ticket_key)
        .first()
    )
    if ticket is None:
        return None
    if viewer is not None:
        if not can_view_ticket(viewer, ticket):
            return None
    return ticket
