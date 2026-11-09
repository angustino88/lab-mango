"""Transition ticket status command use case."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType, ResolutionCode, SystemState
from core.support_desk.exceptions import (
    ConcurrencyConflictError,
    InvalidFieldValueError,
    InvalidStatusTransitionError,
    MissingResolutionSummaryError,
    MissingTransitionReasonError,
    PermissionDeniedError,
    ReopenWindowExpiredError,
)
from core.support_desk.features.tickets.application.notifications import queue_ticket_notifications
from core.support_desk.features.tickets.application.policies import can_transition_ticket, is_support_agent
from core.support_desk.features.tickets.application.shared import (
    actor_display_name,
    actor_or_none,
    get_ticket_for_actor,
)
from core.support_desk.features.tickets.application.sla import apply_status_sla_transition, compute_deadlines
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.transition import SupportStatusTransition

_RESOLUTION_CODES = {code.value for code in ResolutionCode}


@dataclass(frozen=True, slots=True)
class TransitionTicketInput:
    ticket_key: str
    to_status_id: int
    version: int
    reason: str = ""
    resolution_summary: str = ""
    root_cause: str = ""
    resolution_code: str = ""


def transition_ticket(command: TransitionTicketInput, *, actor: Any) -> SupportTicket:
    """Execute a validated status transition on a ticket."""
    ticket = get_ticket_for_actor(
        command.ticket_key,
        actor,
        select_related=("status", "category", "priority", "requester", "assignee", "team"),
    )

    to_status = SupportStatus.objects.filter(pk=command.to_status_id, is_active=True).first()
    if not to_status:
        raise InvalidStatusTransitionError(f"Target status {command.to_status_id} does not exist or is inactive.")

    if ticket.status_id == to_status.id:
        return ticket

    transition = (
        SupportStatusTransition.objects.select_related("from_status", "to_status")
        .filter(from_status=ticket.status, to_status=to_status)
        .first()
    )
    if not transition:
        raise InvalidStatusTransitionError(
            f"Transition from '{ticket.status.name}' to '{to_status.name}' is not permitted."
        )

    # Check permission and reopen window
    is_reopen = (
        ticket.status.system_state == SystemState.DONE.value
        and to_status.system_state == SystemState.OPEN.value
    )

    if not can_transition_ticket(actor, ticket, transition):
        if is_reopen:
            raise ReopenWindowExpiredError("The window to reopen this ticket has expired, or permission is denied.")
        raise PermissionDeniedError(
            f"You do not have permission to transition this ticket from '{ticket.status.name}' to '{to_status.name}'."
        )

    # Check required inputs
    if transition.requires_reason and not command.reason.strip():
        raise MissingTransitionReasonError(f"A reason is required when transitioning to '{to_status.name}'.")

    if is_reopen and not command.reason.strip():
        raise MissingTransitionReasonError("A reason is required to reopen this ticket.")

    if transition.requires_resolution and not command.resolution_summary.strip():
        raise MissingResolutionSummaryError("A resolution summary is required to resolve this ticket.")

    if command.resolution_code and command.resolution_code not in _RESOLUTION_CODES:
        raise InvalidFieldValueError(f"Invalid resolution code '{command.resolution_code}'.")

    now = timezone.now()
    app_settings = SupportSettings.get_solo()
    updates: dict[str, Any] = {
        "status": to_status,
        "version": ticket.version + 1,
    }

    # SLA clocks: pause/resume when crossing a "pauses_sla" status boundary
    sla_updates, sla_event = apply_status_sla_transition(ticket, ticket.status, to_status, now=now)
    updates.update(sla_updates)

    # Open -> In Progress: auto-assign if currently unassigned and actor is agent
    if (
        ticket.status.system_state == SystemState.OPEN.value
        and to_status.system_state == SystemState.ACTIVE.value
        and not ticket.assignee
        and is_support_agent(actor)
    ):
        updates["assignee"] = actor

    # Moving to a "done" status
    has_resolution_input = bool(command.resolution_summary or command.resolution_code)
    resolving = to_status.system_state == SystemState.DONE.value and (
        transition.requires_resolution or has_resolution_input
    )
    if to_status.system_state == SystemState.DONE.value:
        if resolving:
            updates["resolution_summary"] = command.resolution_summary
            updates["root_cause"] = command.root_cause
            updates["resolution_code"] = command.resolution_code
            updates["resolved_at"] = now
            updates["resolved_by"] = actor_or_none(actor)
        elif ticket.resolved_at is None:
            # Closed/cancelled without an explicit resolution: still stamp when work ended.
            updates["resolved_at"] = now
            updates["resolved_by"] = actor_or_none(actor)
        if to_status.is_final:
            updates["closed_at"] = now
        # Any pending SLA clock is satisfied by finishing; make sure a paused clock does not linger.
        updates.setdefault("sla_paused_at", None)

    # Reopening
    if is_reopen:
        updates["resolved_at"] = None
        updates["closed_at"] = None
        updates["resolved_by"] = None
        updates["resolution_code"] = ""
        updates["reopen_count"] = ticket.reopen_count + 1
        # Fresh resolution clock from the reopen moment (response clock is not restarted).
        deadlines = compute_deadlines(ticket.priority, start=now, enabled=app_settings.sla_enabled)
        updates["resolution_due_at"] = deadlines["resolution_due_at"]
        updates["resolution_breached_at"] = None
        updates["sla_paused_at"] = now if to_status.pauses_sla else None

    with transaction.atomic():
        rows = SupportTicket.objects.filter(
            pk=ticket.pk,
            version=command.version,
        ).update(**updates)

        if rows == 0:
            raise ConcurrencyConflictError(
                "Ticket has been modified concurrently by another user. Please refresh and retry."
            )

        previous_resolution_summary = ticket.resolution_summary
        ticket = get_ticket_for_actor(
            command.ticket_key,
            actor,
            select_related=("status", "category", "priority", "requester", "assignee", "team"),
        )

        actor_name = actor_display_name(actor, default="System")

        if is_reopen:
            event_type = ActivityEventType.REOPENED.value
            event_name = "ticket_reopened"
        elif resolving:
            event_type = ActivityEventType.RESOLVED.value
            event_name = "ticket_resolved"
        else:
            event_type = ActivityEventType.STATUS_CHANGED.value
            event_name = "status_changed"

        activity_payload = {
            "from_status": transition.from_status.name,
            "to_status": to_status.name,
            "reason": command.reason,
            "resolution_summary": command.resolution_summary,
            "root_cause": command.root_cause,
            "resolution_code": command.resolution_code,
        }
        if is_reopen:
            activity_payload["previous_resolution_summary"] = previous_resolution_summary

        TicketActivity.objects.create(
            ticket=ticket,
            event_type=event_type,
            actor=actor_or_none(actor),
            actor_name=actor_name,
            payload=activity_payload,
        )

        if sla_event:
            TicketActivity.objects.create(
                ticket=ticket,
                event_type=(
                    ActivityEventType.SLA_PAUSED.value if sla_event == "paused" else ActivityEventType.SLA_RESUMED.value
                ),
                actor=actor_or_none(actor),
                actor_name=actor_name,
                payload={"status": to_status.name},
            )

        queue_ticket_notifications(ticket, event_name, actor, extra={"reason": command.reason})

    return ticket
