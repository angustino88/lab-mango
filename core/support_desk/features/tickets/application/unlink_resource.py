"""Unlink resource from support ticket command use case."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
    TicketNotFoundError,
)
from core.support_desk.features.tickets.application.policies import can_unlink_resource
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.ticket import SupportTicket


@dataclass(frozen=True, slots=True)
class UnlinkResourceInput:
    ticket_key: str
    resource_type: str
    resource_id: str
    reason: str = ""


def unlink_resource(command: UnlinkResourceInput, *, actor: Any) -> TicketResourceLink:
    """Soft-unlink a resource from a support ticket (never hard-deleted)."""
    if not can_unlink_resource(actor):
        raise PermissionDeniedError("Only support agents and administrators can unlink resources.")

    ticket = SupportTicket.objects.filter(key=command.ticket_key).first()
    if not ticket:
        raise TicketNotFoundError(f"Ticket {command.ticket_key} not found.")

    link = TicketResourceLink.objects.filter(
        ticket=ticket,
        resource_type=command.resource_type,
        resource_id=command.resource_id,
        is_active=True,
    ).first()
    if not link:
        raise ResourceNotFoundError(
            f"Active link for {command.resource_type} {command.resource_id} not found on ticket {ticket.key}."
        )

    with transaction.atomic():
        link.is_active = False
        link.unlinked_by = actor
        link.unlinked_at = timezone.now()
        link.unlink_reason = command.reason
        link.save(update_fields=["is_active", "unlinked_by", "unlinked_at", "unlink_reason"])

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.RESOURCE_UNLINKED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "resource_type": command.resource_type,
                "resource_id": str(command.resource_id),
                "reason": command.reason,
            },
        )

    return link
