"""Transactional outbox notification dispatch logic for Support Desk."""

import uuid
from collections.abc import Iterable
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from core.support_desk.contracts import OutboxChannel, OutboxStatus
from core.support_desk.features.tickets.application.shared import actor_display_name
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.watcher import TicketWatcher
from core.users.public import LabsRole, users_holding_labs_role

User = get_user_model()

BOTH_CHANNELS = (OutboxChannel.EMAIL, OutboxChannel.IN_APP)
IN_APP_ONLY = (OutboxChannel.IN_APP,)


def _get_support_agents_and_admins() -> list[Any]:
    """Active support agents and administrators: Labs coordinators, admins and superusers."""
    return list(users_holding_labs_role(LabsRole.COORDINATOR))


def _team_or_all_agents(ticket: SupportTicket) -> list[Any]:
    """Agents who should hear about a new/unowned ticket: its team if it has one, otherwise everyone."""
    team = getattr(ticket, "team", None)
    if team is not None:
        members = list(team.members.filter(is_active=True))
        if team.lead and team.lead.is_active and team.lead not in members:
            members.append(team.lead)
        if members:
            return members
    return _get_support_agents_and_admins()


def _watchers(ticket: SupportTicket) -> list[Any]:
    return [w.user for w in TicketWatcher.objects.filter(ticket=ticket, user__is_active=True).select_related("user")]


def queue_notification(
    *,
    event_id: str,
    recipient: Any,
    channel: OutboxChannel,
    payload: dict[str, Any],
) -> None:
    """Create an outbox record if not already queued for this event/recipient/channel."""
    NotificationOutbox.objects.get_or_create(
        event_id=event_id,
        recipient=recipient,
        channel=channel.value,
        defaults={
            "payload": payload,
            "status": OutboxStatus.PENDING.value,
        },
    )


def _fan_out(
    event_id: str,
    recipients: Iterable[Any],
    channels: Iterable[OutboxChannel],
    payload: dict[str, Any],
    *,
    exclude_pk: int | None,
) -> None:
    """Queue ``payload`` for each distinct recipient (never the actor) on each channel."""
    seen: set[int] = set()
    for recipient in recipients:
        pk = getattr(recipient, "pk", None)
        if pk is None or pk == exclude_pk or pk in seen:
            continue
        seen.add(pk)
        for channel in channels:
            queue_notification(event_id=event_id, recipient=recipient, channel=channel, payload=payload)


def queue_ticket_notifications(
    ticket: SupportTicket,
    event_name: str,
    actor: Any,
    extra: dict[str, Any] | None = None,
) -> None:
    """Queue appropriate notifications for a ticket lifecycle event inside the active transaction.

    Watchers follow every public event on the ticket; internal notes only go to agents.
    """
    event_id = str(uuid.uuid4())
    actor_pk = getattr(actor, "pk", None)
    base_payload = {
        "event_id": event_id,
        "event_name": event_name,
        "ticket_key": ticket.key,
        "ticket_subject": ticket.subject,
        "actor_id": actor_pk,
        "actor_name": actor_display_name(actor, default="System"),
        "deep_link": f"/support/tickets/{ticket.key}",
        **(extra or {}),
    }

    def payload(subject: str, message: str, **more: Any) -> dict[str, Any]:
        return {**base_payload, "subject": f"[{ticket.key}] {subject}", "message": message, **more}

    def send(
        recipients: Iterable[Any],
        channels: Iterable[OutboxChannel],
        body: dict[str, Any],
        *,
        notify_actor: bool = False,
    ) -> None:
        _fan_out(event_id, recipients, channels, body, exclude_pk=None if notify_actor else actor_pk)

    with transaction.atomic():
        if event_name == "ticket_created":
            send(
                [ticket.requester],
                BOTH_CHANNELS,
                payload(f"Ticket Created: {ticket.subject}", f"Your ticket [{ticket.key}] has been submitted successfully."),
                notify_actor=True,  # confirmation goes to the requester even when they filed it themselves
            )
            send(
                _team_or_all_agents(ticket),
                IN_APP_ONLY,
                payload(f"New Support Ticket: {ticket.subject}", f"A new support ticket [{ticket.key}] has been opened."),
            )
            send(_watchers(ticket), IN_APP_ONLY, payload(f"Watching: {ticket.subject}", f"You are watching [{ticket.key}]."))

        elif event_name == "ticket_assigned":
            if ticket.assignee:
                send(
                    [ticket.assignee],
                    BOTH_CHANNELS,
                    payload(f"Ticket Assigned: {ticket.subject}", f"You have been assigned to ticket [{ticket.key}]."),
                    notify_actor=True,  # self-assignment still gets a confirmation
                )
            send(
                [ticket.requester, *_watchers(ticket)],
                BOTH_CHANNELS,
                payload(
                    f"Assignee Updated: {ticket.subject}",
                    f"Ticket [{ticket.key}] is now assigned to {actor_display_name(ticket.assignee, default='nobody')}.",
                ),
            )

        elif event_name == "ticket_routed":
            send(
                _team_or_all_agents(ticket),
                IN_APP_ONLY,
                payload(f"Routed to your team: {ticket.subject}", f"Ticket [{ticket.key}] was routed to your queue."),
            )

        elif event_name == "comment_added":
            if extra and extra.get("visibility") == "internal":
                # Internal note: assignee, prior commenting agents and the team lead (in-app only)
                recipients: list[Any] = []
                if ticket.assignee:
                    recipients.append(ticket.assignee)
                prior_author_ids = (
                    ticket.comments.exclude(author_id=actor_pk).values_list("author_id", flat=True).distinct()
                )
                recipients.extend(User.objects.filter(pk__in=list(prior_author_ids), is_active=True))
                from core.support_desk.features.tickets.application.policies import is_support_agent

                send(
                    [r for r in recipients if is_support_agent(r)],
                    IN_APP_ONLY,
                    payload(f"New Internal Note: {ticket.subject}", f"A new internal note was added to [{ticket.key}]."),
                )
            else:
                send(
                    [ticket.requester, ticket.assignee, *_watchers(ticket)],
                    BOTH_CHANNELS,
                    payload(f"New Comment: {ticket.subject}", f"A new comment was added to ticket [{ticket.key}]."),
                )

        elif event_name == "status_changed":
            send(
                [ticket.requester, ticket.assignee, *_watchers(ticket)],
                BOTH_CHANNELS,
                payload(
                    f"Status Changed to {ticket.status.name}: {ticket.subject}",
                    f"Ticket [{ticket.key}] status changed to {ticket.status.name}.",
                ),
            )

        elif event_name == "ticket_resolved":
            send(
                [ticket.requester, *_watchers(ticket)],
                BOTH_CHANNELS,
                payload(
                    f"Resolved: {ticket.subject}",
                    f"Your ticket [{ticket.key}] has been marked Resolved.\n\nResolution:\n{ticket.resolution_summary}",
                    reopen_link=f"/support/tickets/{ticket.key}/reopen",
                    csat_link=f"/support/tickets/{ticket.key}/csat",
                ),
                notify_actor=True,
            )

        elif event_name == "ticket_reopened":
            recipients = [ticket.assignee] if ticket.assignee else _team_or_all_agents(ticket)
            send(
                [*recipients, *_watchers(ticket)],
                BOTH_CHANNELS,
                payload(f"Ticket Reopened: {ticket.subject}", f"Ticket [{ticket.key}] has been reopened."),
            )

        elif event_name == "sla_breached":
            sla_kind = (extra or {}).get("sla_kind", "resolution")
            lead = ticket.team.lead if getattr(ticket, "team", None) else None
            send(
                [ticket.assignee, lead] if ticket.assignee or lead else _team_or_all_agents(ticket),
                BOTH_CHANNELS,
                payload(
                    f"SLA Breached ({sla_kind}): {ticket.subject}",
                    f"Ticket [{ticket.key}] has breached its {sla_kind} SLA.",
                ),
            )
