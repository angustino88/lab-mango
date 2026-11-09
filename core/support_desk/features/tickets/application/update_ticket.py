"""Update support ticket command use case."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType, SystemState, TicketType
from core.support_desk.exceptions import (
    ConcurrencyConflictError,
    InvalidFieldValueError,
    PermissionDeniedError,
    TicketNotFoundError,
)
from core.support_desk.features.tickets.application.notifications import queue_ticket_notifications
from core.support_desk.features.tickets.application.policies import (
    can_change_category_or_priority,
    can_modify_ticket_fields,
    can_triage_ticket,
    can_view_ticket,
)
from core.support_desk.features.tickets.application.shared import actor_display_name
from core.support_desk.features.tickets.application.sla import compute_deadlines
from core.support_desk.features.tickets.application.triage import (
    get_or_create_labels,
    label_names,
    normalize_label_names,
    validate_impact_urgency,
    validate_parent,
)
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket

_TICKET_TYPES = {t.value for t in TicketType}


@dataclass(frozen=True, slots=True)
class UpdateTicketInput:
    """Partial update. ``None`` means "leave unchanged"; use the ``clear_*`` flags to blank nullable fields."""

    ticket_key: str
    version: int
    subject: str | None = None
    description: str | None = None
    category_id: int | None = None
    priority_id: int | None = None
    ticket_type: str | None = None
    impact: str | None = None
    urgency: str | None = None
    external_reference: str | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    # Agent-only triage fields
    team_id: int | None = None
    clear_team: bool = False
    labels: tuple[str, ...] | None = None
    parent_key: str | None = None
    clear_parent: bool = False


def update_ticket(command: UpdateTicketInput, *, actor: Any) -> SupportTicket:
    """Apply partial updates to a ticket with optimistic locking and audit logging."""
    ticket = (
        SupportTicket.objects.select_related("category", "priority", "status", "requester", "team", "parent")
        .filter(key=command.ticket_key)
        .first()
    )
    if not ticket or not can_view_ticket(actor, ticket):
        raise TicketNotFoundError(f"Ticket {command.ticket_key} not found.")

    if not can_modify_ticket_fields(actor, ticket):
        raise PermissionDeniedError("You do not have permission to modify this ticket.")

    is_agent = can_triage_ticket(actor)
    changes: dict[str, dict[str, Any]] = {}
    updates: dict[str, Any] = {}
    priority_changed: SupportPriority | None = None
    new_team: SupportTeam | None = None
    team_changed = False
    new_labels = None

    if command.subject is not None and command.subject != ticket.subject:
        changes["subject"] = {"old": ticket.subject, "new": command.subject}
        updates["subject"] = command.subject

    if command.description is not None and command.description != ticket.description:
        changes["description"] = {"old": ticket.description, "new": command.description}
        updates["description"] = command.description

    if command.category_id is not None and command.category_id != ticket.category_id:
        if not can_change_category_or_priority(actor):
            raise PermissionDeniedError("Only support agents and administrators can change category.")
        category = SupportCategory.objects.filter(pk=command.category_id, is_active=True).first()
        if not category:
            raise PermissionDeniedError(f"Category {command.category_id} not found.")
        changes["category"] = {"old": ticket.category.name, "new": category.name}
        updates["category"] = category

    if command.priority_id is not None and command.priority_id != ticket.priority_id:
        if not can_change_category_or_priority(actor):
            raise PermissionDeniedError("Only support agents and administrators can change priority.")
        priority = SupportPriority.objects.filter(pk=command.priority_id, is_active=True).first()
        if not priority:
            raise PermissionDeniedError(f"Priority {command.priority_id} not found.")
        changes["priority"] = {"old": ticket.priority.name, "new": priority.name}
        updates["priority"] = priority
        priority_changed = priority

    if command.ticket_type is not None and command.ticket_type != ticket.ticket_type:
        if command.ticket_type not in _TICKET_TYPES:
            raise InvalidFieldValueError(f"Invalid ticket type '{command.ticket_type}'.")
        changes["ticket_type"] = {"old": ticket.ticket_type, "new": command.ticket_type}
        updates["ticket_type"] = command.ticket_type

    validate_impact_urgency(command.impact, command.urgency)
    if command.impact is not None and command.impact != ticket.impact:
        changes["impact"] = {"old": ticket.impact, "new": command.impact}
        updates["impact"] = command.impact
    if command.urgency is not None and command.urgency != ticket.urgency:
        changes["urgency"] = {"old": ticket.urgency, "new": command.urgency}
        updates["urgency"] = command.urgency

    if command.external_reference is not None and command.external_reference != ticket.external_reference:
        changes["external_reference"] = {"old": ticket.external_reference, "new": command.external_reference}
        updates["external_reference"] = command.external_reference

    if command.clear_due_date and ticket.due_date is not None:
        changes["due_date"] = {"old": ticket.due_date.isoformat(), "new": None}
        updates["due_date"] = None
    elif command.due_date is not None and command.due_date != ticket.due_date:
        changes["due_date"] = {
            "old": ticket.due_date.isoformat() if ticket.due_date else None,
            "new": command.due_date.isoformat(),
        }
        updates["due_date"] = command.due_date

    # --- agent-only triage -------------------------------------------------
    wants_triage = (
        command.team_id is not None
        or command.clear_team
        or command.labels is not None
        or command.parent_key is not None
        or command.clear_parent
    )
    if wants_triage and not is_agent:
        raise PermissionDeniedError("Only support agents and administrators can change team, labels or parent.")

    if command.clear_team and ticket.team_id is not None:
        changes["team"] = {"old": ticket.team.name, "new": None}
        updates["team"] = None
        team_changed = True
    elif command.team_id is not None and command.team_id != ticket.team_id:
        new_team = SupportTeam.objects.filter(pk=command.team_id, is_active=True).first()
        if not new_team:
            raise InvalidFieldValueError(f"Team {command.team_id} is not active or does not exist.")
        changes["team"] = {"old": ticket.team.name if ticket.team else None, "new": new_team.name}
        updates["team"] = new_team
        team_changed = True

    if command.labels is not None:
        wanted = normalize_label_names(command.labels)
        current = label_names(ticket)
        if sorted(wanted) != current:
            changes["labels"] = {"old": current, "new": sorted(wanted)}
            new_labels = wanted

    if command.clear_parent and ticket.parent_id is not None:
        changes["parent"] = {"old": ticket.parent.key, "new": None}
        updates["parent"] = None
    elif command.parent_key is not None and (ticket.parent is None or ticket.parent.key != command.parent_key):
        parent = SupportTicket.objects.filter(key=command.parent_key).first()
        if not parent:
            raise TicketNotFoundError(f"Parent ticket {command.parent_key} not found.")
        validate_parent(ticket, parent)
        changes["parent"] = {"old": ticket.parent.key if ticket.parent else None, "new": parent.key}
        updates["parent"] = parent

    if not updates and new_labels is None:
        return ticket

    # A priority change re-bases the open SLA windows on the new targets.
    if priority_changed and ticket.status.system_state != SystemState.DONE.value:
        deadlines = compute_deadlines(
            priority_changed,
            start=ticket.created_at,
            paused_seconds=ticket.sla_paused_seconds,
            enabled=SupportSettings.get_solo().sla_enabled,
        )
        if ticket.first_response_at is None:
            updates["response_due_at"] = deadlines["response_due_at"]
        updates["resolution_due_at"] = deadlines["resolution_due_at"]
        # Moving to a more relaxed priority can un-breach a clock; moving to a stricter one is judged on the next scan.
        now = timezone.now()
        if deadlines["resolution_due_at"] and deadlines["resolution_due_at"] > now:
            updates["resolution_breached_at"] = None
        if ticket.first_response_at is None and deadlines["response_due_at"] and deadlines["response_due_at"] > now:
            updates["response_breached_at"] = None

    updates["version"] = ticket.version + 1

    with transaction.atomic():
        rows_updated = SupportTicket.objects.filter(
            pk=ticket.pk,
            version=command.version,
        ).update(**updates)

        if rows_updated == 0:
            raise ConcurrencyConflictError(
                "Ticket has been modified concurrently by another user. Please refresh and retry."
            )

        if new_labels is not None:
            ticket.labels.set(get_or_create_labels(new_labels))

        ticket.refresh_from_db()

        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.UPDATED.value,
            actor=actor,
            actor_name=actor_display_name(actor),
            payload={"changes": changes},
        )

        if team_changed and ticket.team_id:
            queue_ticket_notifications(ticket, "ticket_routed", actor)

    return ticket
