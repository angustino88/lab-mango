"""Add comment to support ticket command use case."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType, CommentVisibility, SystemState
from core.support_desk.exceptions import PermissionDeniedError
from core.support_desk.features.tickets.application.notifications import queue_ticket_notifications
from core.support_desk.features.tickets.application.policies import can_add_comment, is_support_agent
from core.support_desk.features.tickets.application.shared import actor_display_name, get_ticket_for_actor
from core.support_desk.features.tickets.application.sla import apply_status_sla_transition
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.comment import TicketComment
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.ticket import SupportTicket


@dataclass(frozen=True, slots=True)
class AddCommentInput:
    ticket_key: str
    body: str
    visibility: str = CommentVisibility.PUBLIC.value


def add_comment(command: AddCommentInput, *, actor: Any) -> TicketComment:
    """Add a public or internal comment to a ticket."""
    ticket = get_ticket_for_actor(
        command.ticket_key,
        actor,
        select_related=("status", "requester", "assignee", "category", "priority", "team"),
    )

    if not can_add_comment(actor, ticket, command.visibility):
        raise PermissionDeniedError("You do not have permission to post this comment.")

    now = timezone.now()
    is_public = command.visibility == CommentVisibility.PUBLIC.value
    with transaction.atomic():
        comment = TicketComment.objects.create(
            ticket=ticket,
            author=actor,
            body=command.body,
            visibility=command.visibility,
        )

        ticket_updates: dict[str, Any] = {}
        # First *customer-visible* agent reply stops the response SLA clock (internal notes never count).
        if is_public and is_support_agent(actor) and actor.pk != ticket.requester_id and ticket.first_response_at is None:
            ticket_updates["first_response_at"] = now

        # Waiting -> In Progress auto-transition when the requester replies publicly
        auto_status: SupportStatus | None = None
        if (
            ticket.status.system_state == SystemState.WAITING.value
            and is_public
            and ticket.requester_id == actor.pk
        ):
            auto_status = SupportStatus.objects.filter(
                system_state=SystemState.ACTIVE.value,
                is_active=True,
            ).first()
            if auto_status:
                ticket_updates["status"] = auto_status
                ticket_updates["version"] = ticket.version + 1
                sla_updates, _ = apply_status_sla_transition(ticket, ticket.status, auto_status, now=now)
                ticket_updates.update(sla_updates)

        previous_status_name = ticket.status.name
        if ticket_updates:
            SupportTicket.objects.filter(pk=ticket.pk).update(**ticket_updates)
            ticket.refresh_from_db()

        actor_name = actor_display_name(actor)
        if auto_status is not None:
            TicketActivity.objects.create(
                ticket=ticket,
                event_type=ActivityEventType.STATUS_CHANGED.value,
                actor=actor,
                actor_name=actor_name,
                payload={
                    "from_status": previous_status_name,
                    "to_status": auto_status.name,
                    "reason": "Automatic transition on requester reply.",
                },
            )

        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.COMMENT_ADDED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "comment_id": comment.pk,
                "visibility": comment.visibility,
                "body_preview": comment.body[:100],
            },
        )

        queue_ticket_notifications(
            ticket,
            "comment_added",
            actor,
            extra={"visibility": command.visibility, "comment_id": comment.pk},
        )

    return comment
