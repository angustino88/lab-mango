"""Link / unlink tickets to each other (relates to, duplicates, blocks, caused by)."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from core.support_desk.contracts import ActivityEventType, LinkType
from core.support_desk.exceptions import (
    DuplicateTicketLinkError,
    InvalidTicketLinkError,
    PermissionDeniedError,
    RecordNotFoundError,
)
from core.support_desk.features.tickets.application.policies import can_link_tickets
from core.support_desk.features.tickets.application.shared import actor_display_name, get_ticket_for_actor
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.ticket_link import TicketLink

_LINK_TYPES = {t.value for t in LinkType}


@dataclass(frozen=True, slots=True)
class LinkTicketsInput:
    ticket_key: str
    target_key: str
    link_type: str


@dataclass(frozen=True, slots=True)
class UnlinkTicketsInput:
    ticket_key: str
    link_id: int


def link_tickets(command: LinkTicketsInput, *, actor: Any) -> TicketLink:
    if not can_link_tickets(actor):
        raise PermissionDeniedError("Only support agents and administrators can link tickets.")
    if command.link_type not in _LINK_TYPES:
        raise InvalidTicketLinkError(f"Unsupported link type '{command.link_type}'.")
    if command.ticket_key == command.target_key:
        raise InvalidTicketLinkError("A ticket cannot be linked to itself.")

    source = get_ticket_for_actor(command.ticket_key, actor)
    target = get_ticket_for_actor(command.target_key, actor)

    # "relates to" is symmetric: refuse the mirrored duplicate.
    mirrored = command.link_type == LinkType.RELATES_TO.value and TicketLink.objects.filter(
        source=target, target=source, link_type=command.link_type
    ).exists()
    if mirrored or TicketLink.objects.filter(source=source, target=target, link_type=command.link_type).exists():
        raise DuplicateTicketLinkError(f"{source.key} is already linked to {target.key} ({command.link_type}).")

    with transaction.atomic():
        link = TicketLink.objects.create(source=source, target=target, link_type=command.link_type, created_by=actor)
        payload = {
            "link_id": link.pk,
            "link_type": link.link_type,
            "source": source.key,
            "target": target.key,
        }
        name = actor_display_name(actor)
        for ticket in (source, target):
            TicketActivity.objects.create(
                ticket=ticket,
                event_type=ActivityEventType.TICKET_LINKED.value,
                actor=actor,
                actor_name=name,
                payload=payload,
            )
    return link


def unlink_tickets(command: UnlinkTicketsInput, *, actor: Any) -> None:
    if not can_link_tickets(actor):
        raise PermissionDeniedError("Only support agents and administrators can unlink tickets.")
    ticket = get_ticket_for_actor(command.ticket_key, actor)
    link = (
        TicketLink.objects.select_related("source", "target")
        .filter(pk=command.link_id)
        .filter(source=ticket)
        .first()
    ) or (
        TicketLink.objects.select_related("source", "target").filter(pk=command.link_id, target=ticket).first()
    )
    if link is None:
        raise RecordNotFoundError(f"Link {command.link_id} not found on ticket {ticket.key}.")

    with transaction.atomic():
        payload = {
            "link_id": link.pk,
            "link_type": link.link_type,
            "source": link.source.key,
            "target": link.target.key,
        }
        tickets = (link.source, link.target)
        link.delete()
        name = actor_display_name(actor)
        for item in tickets:
            TicketActivity.objects.create(
                ticket=item,
                event_type=ActivityEventType.TICKET_UNLINKED.value,
                actor=actor,
                actor_name=name,
                payload=payload,
            )
