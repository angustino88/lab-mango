"""Assign ticket command use case."""

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    ConcurrencyConflictError,
    PermissionDeniedError,
    TicketNotFoundError,
)
from core.support_desk.features.tickets.application.notifications import queue_ticket_notifications
from core.support_desk.features.tickets.application.policies import can_assign_ticket
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.ticket import SupportTicket

User = get_user_model()


@dataclass(frozen=True, slots=True)
class AssignTicketInput:
    ticket_key: str
    assignee_id: int | None
    version: int | None = None


def assign_ticket(command: AssignTicketInput, *, actor: Any) -> SupportTicket:
    """Assign or reassign a support ticket."""
    if not can_assign_ticket(actor):
        raise PermissionDeniedError("Only support agents and administrators can assign tickets.")

    ticket = (
        SupportTicket.objects.select_related("assignee", "requester", "status", "category", "priority")
        .filter(key=command.ticket_key)
        .first()
    )
    if not ticket:
        raise TicketNotFoundError(f"Ticket {command.ticket_key} not found.")

    new_assignee = None
    if command.assignee_id is not None:
        new_assignee = User.objects.filter(pk=command.assignee_id, is_active=True).first()
        if not new_assignee:
            raise PermissionDeniedError(f"User {command.assignee_id} not found.")

    old_assignee_name = (
        ticket.assignee.get_full_name() or ticket.assignee.username if ticket.assignee else "Unassigned"
    )
    new_assignee_name = (
        new_assignee.get_full_name() or new_assignee.username if new_assignee else "Unassigned"
    )

    if ticket.assignee_id == (new_assignee.pk if new_assignee else None):
        return ticket

    filter_kwargs: dict[str, Any] = {"pk": ticket.pk}
    if command.version is not None:
        filter_kwargs["version"] = command.version

    with transaction.atomic():
        rows = SupportTicket.objects.filter(**filter_kwargs).update(
            assignee=new_assignee,
            version=ticket.version + 1,
        )
        if rows == 0:
            raise ConcurrencyConflictError(
                "Ticket has been modified concurrently by another user. Please refresh and retry."
            )

        ticket.refresh_from_db()

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        event_type = (
            ActivityEventType.ASSIGNED.value if new_assignee else ActivityEventType.UNASSIGNED.value
        )
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=event_type,
            actor=actor,
            actor_name=actor_name,
            payload={
                "old_assignee": old_assignee_name,
                "new_assignee": new_assignee_name,
                "new_assignee_id": new_assignee.pk if new_assignee else None,
            },
        )

        queue_ticket_notifications(ticket, "ticket_assigned", actor)

    return ticket
