"""Create support ticket command use case."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.support_desk.contracts import ActivityEventType, SystemState, TicketSource, TicketType
from core.support_desk.exceptions import (
    InvalidFieldValueError,
    PermissionDeniedError,
    ResourceAccessDeniedError,
    TicketCreationDisabledError,
    TicketNotFoundError,
)
from core.support_desk.features.tickets.application.adapters import get_adapter
from core.support_desk.features.tickets.application.notifications import queue_ticket_notifications
from core.support_desk.features.tickets.application.policies import (
    can_create_ticket_on_behalf,
    can_link_resource,
    can_triage_ticket,
)
from core.support_desk.features.tickets.application.shared import actor_display_name
from core.support_desk.features.tickets.application.sla import compute_deadlines
from core.support_desk.features.tickets.application.triage import (
    get_or_create_labels,
    resolve_priority,
    validate_impact_urgency,
    validate_parent,
)
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.watcher import TicketWatcher

User = get_user_model()

_TICKET_TYPES = {t.value for t in TicketType}
_SOURCES = {s.value for s in TicketSource if s is not TicketSource.SYSTEM}


@dataclass(frozen=True, slots=True)
class CreateTicketInput:
    subject: str
    description: str
    category_id: int
    priority_id: int | None = None
    linked_resources: tuple[tuple[str, str], ...] = ()
    assignee_id: int | None = None
    on_behalf_of_id: int | None = None
    idempotency_key: str | None = None
    ticket_type: str | None = None
    impact: str = ""
    urgency: str = ""
    source: str = TicketSource.WEB.value
    external_reference: str = ""
    due_date: date | None = None
    # Triage fields (support agents / administrators only)
    team_id: int | None = None
    labels: tuple[str, ...] = ()
    parent_key: str | None = None
    watcher_ids: tuple[int, ...] = ()


def _resolve_initial_status() -> SupportStatus:
    initial_status = SupportStatus.objects.filter(is_initial=True, is_active=True).first()
    if not initial_status:
        initial_status = SupportStatus.objects.filter(system_state=SystemState.OPEN.value, is_active=True).first()
    if not initial_status:
        initial_status = SupportStatus.objects.filter(is_active=True).first()
    if not initial_status:
        raise TicketCreationDisabledError("No active status is configured for support tickets.")
    return initial_status


def _has_active_priority() -> bool:
    return SupportPriority.objects.filter(is_active=True).exists()


def create_ticket(command: CreateTicketInput, *, actor: Any) -> SupportTicket:
    """Create a new support ticket within an atomic transaction."""
    if not actor or not actor.is_authenticated:
        raise PermissionDeniedError("Authentication is required to create a ticket.")

    # Idempotency check
    if command.idempotency_key:
        existing = SupportTicket.objects.filter(idempotency_key=command.idempotency_key).first()
        if existing:
            return existing

    app_settings = SupportSettings.get_solo()

    # FR-26: Block creation if no category or priority is defined
    has_active_category = SupportCategory.objects.filter(is_active=True).exists()
    has_active_priority = _has_active_priority()
    if not has_active_category or not has_active_priority:
        raise TicketCreationDisabledError(
            "Ticket creation is disabled until an administrator defines at least one category and one priority."
        )

    category = (
        SupportCategory.objects.select_related("default_team")
        .filter(pk=command.category_id, is_active=True)
        .first()
    )
    if not category:
        raise TicketCreationDisabledError(f"Category {command.category_id} is not active or does not exist.")

    is_agent = can_triage_ticket(actor)

    ticket_type = command.ticket_type or app_settings.default_ticket_type
    if ticket_type not in _TICKET_TYPES:
        raise InvalidFieldValueError(f"Invalid ticket type '{ticket_type}'.")
    if command.source not in _SOURCES:
        raise InvalidFieldValueError(f"Invalid source '{command.source}'.")
    validate_impact_urgency(command.impact, command.urgency)

    # Priority: requesters may be restricted to describing impact/urgency only.
    explicit_priority_id = command.priority_id
    if explicit_priority_id and not is_agent and not app_settings.requesters_can_set_priority:
        explicit_priority_id = None
    priority = resolve_priority(
        explicit_id=explicit_priority_id,
        impact=command.impact,
        urgency=command.urgency,
    )

    initial_status = _resolve_initial_status()

    # Determine requester
    requester = actor
    if command.on_behalf_of_id:
        if not can_create_ticket_on_behalf(actor):
            raise PermissionDeniedError("Only support agents and administrators can submit tickets on behalf of others.")
        target_user = User.objects.filter(pk=command.on_behalf_of_id, is_active=True).first()
        if not target_user:
            raise PermissionDeniedError(f"User {command.on_behalf_of_id} not found.")
        requester = target_user

    # Determine assignee
    assignee = None
    if command.assignee_id:
        if not can_create_ticket_on_behalf(actor):
            raise PermissionDeniedError("Only support agents and administrators can pre-assign tickets.")
        assignee = User.objects.filter(pk=command.assignee_id, is_active=True).first()

    # Agent-only triage fields
    if not is_agent and (command.team_id or command.labels or command.parent_key or command.watcher_ids):
        raise PermissionDeniedError("Only support agents and administrators can set team, labels, parent or watchers.")

    team = None
    if command.team_id:
        team = SupportTeam.objects.filter(pk=command.team_id, is_active=True).first()
        if not team:
            raise InvalidFieldValueError(f"Team {command.team_id} is not active or does not exist.")
    elif category.default_team_id and category.default_team.is_active:
        team = category.default_team

    parent = None
    if command.parent_key:
        parent = SupportTicket.objects.filter(key=command.parent_key).first()
        if not parent:
            raise TicketNotFoundError(f"Parent ticket {command.parent_key} not found.")
        validate_parent(None, parent)

    watchers = list(User.objects.filter(pk__in=command.watcher_ids, is_active=True)) if command.watcher_ids else []

    try:
        with transaction.atomic():
            ticket = SupportTicket.objects.create(
                subject=command.subject,
                description=command.description,
                ticket_type=ticket_type,
                source=command.source,
                impact=command.impact or "",
                urgency=command.urgency or "",
                external_reference=command.external_reference,
                due_date=command.due_date,
                category=category,
                priority=priority,
                status=initial_status,
                requester=requester,
                created_by=actor,
                assignee=assignee,
                team=team,
                parent=parent,
                idempotency_key=command.idempotency_key,
            )

            # SLA deadlines are measured from the moment the ticket was created.
            deadlines = compute_deadlines(priority, start=ticket.created_at, enabled=app_settings.sla_enabled)
            for field, value in deadlines.items():
                setattr(ticket, field, value)
            if any(deadlines.values()):
                ticket.save(update_fields=list(deadlines))

            if command.labels:
                ticket.labels.set(get_or_create_labels(command.labels))

            TicketWatcher.objects.bulk_create(
                [TicketWatcher(ticket=ticket, user=user, added_by=actor) for user in watchers if user.pk != requester.pk],
                ignore_conflicts=True,
            )

            # Link resources
            for res_type, res_id in command.linked_resources:
                if not can_link_resource(actor, res_type, res_id):
                    raise ResourceAccessDeniedError(f"You do not have access to link {res_type} {res_id}.")
                adapter = get_adapter(res_type)
                snapshot = adapter.snapshot(res_id)
                TicketResourceLink.objects.create(
                    ticket=ticket,
                    resource_type=res_type,
                    resource_id=str(res_id),
                    snapshot=snapshot,
                    linked_by=actor,
                )

            # Append activity log
            actor_name = actor_display_name(actor)
            activity_payload = {
                "subject": ticket.subject,
                "ticket_type": ticket.ticket_type,
                "category": category.name,
                "priority": priority.name,
                "status": initial_status.name,
                "requester_id": requester.pk,
                "requester_name": getattr(requester, "username", ""),
                "team": team.name if team else "",
                "source": ticket.source,
            }
            if command.impact or command.urgency:
                activity_payload["impact"] = command.impact
                activity_payload["urgency"] = command.urgency
            if parent:
                activity_payload["parent"] = parent.key
            if command.on_behalf_of_id and requester.pk != actor.pk:
                activity_payload["on_behalf_of"] = f"Created by {actor_name} on behalf of {requester.username}"

            TicketActivity.objects.create(
                ticket=ticket,
                event_type=ActivityEventType.CREATED.value,
                actor=actor,
                actor_name=actor_name,
                payload=activity_payload,
            )

            # Outbox notifications
            queue_ticket_notifications(ticket, "ticket_created", actor)
    except IntegrityError:
        # Concurrent retry with the same idempotency key lost the race: hand back the winner.
        if command.idempotency_key:
            existing = SupportTicket.objects.filter(idempotency_key=command.idempotency_key).first()
            if existing:
                return existing
        raise

    return ticket
