"""Link resource to support ticket command use case."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    DuplicateResourceLinkError,
    ResourceAccessDeniedError,
)
from core.support_desk.features.tickets.application.adapters import get_adapter
from core.support_desk.features.tickets.application.policies import can_link_resource
from core.support_desk.features.tickets.application.shared import get_ticket_for_actor
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.resource_link import TicketResourceLink


@dataclass(frozen=True, slots=True)
class LinkResourceInput:
    ticket_key: str
    resource_type: str
    resource_id: str


def link_resource(command: LinkResourceInput, *, actor: Any) -> TicketResourceLink:
    """Link a Lab Mango resource to a support ticket, capturing a point-in-time snapshot."""
    ticket = get_ticket_for_actor(command.ticket_key, actor)

    if not can_link_resource(actor, command.resource_type, command.resource_id):
        raise ResourceAccessDeniedError(
            f"You do not have access to view or link {command.resource_type} {command.resource_id}."
        )

    # FR-9: Reject duplicate active links
    existing_active = TicketResourceLink.objects.filter(
        ticket=ticket,
        resource_type=command.resource_type,
        resource_id=command.resource_id,
        is_active=True,
    ).first()
    if existing_active:
        raise DuplicateResourceLinkError(
            f"{command.resource_type} {command.resource_id} is already linked to ticket {ticket.key}."
        )

    adapter = get_adapter(command.resource_type)
    snapshot = adapter.snapshot(command.resource_id)

    with transaction.atomic():
        link = TicketResourceLink.objects.create(
            ticket=ticket,
            resource_type=command.resource_type,
            resource_id=str(command.resource_id),
            snapshot=snapshot,
            linked_by=actor,
        )

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.RESOURCE_LINKED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "resource_type": command.resource_type,
                "resource_id": str(command.resource_id),
                "snapshot": snapshot,
            },
        )

    return link
