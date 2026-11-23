"""Add, update, and delete ticket work log (effort tracking) use cases."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    InvalidFieldValueError,
    PermissionDeniedError,
    RecordNotFoundError,
)
from core.support_desk.features.tickets.application.policies import (
    can_log_work,
    can_manage_work_log,
)
from core.support_desk.features.tickets.application.shared import (
    actor_display_name,
    get_ticket_for_actor,
)
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.work_log import (
    MAX_WORK_LOG_MINUTES,
    MIN_WORK_LOG_MINUTES,
    TicketWorkLog,
)


def _validate_minutes(minutes: int) -> None:
    if not isinstance(minutes, int) or minutes < MIN_WORK_LOG_MINUTES or minutes > MAX_WORK_LOG_MINUTES:
        raise InvalidFieldValueError(
            f"Time spent must be between {MIN_WORK_LOG_MINUTES} and {MAX_WORK_LOG_MINUTES} minutes."
        )


def _format_minutes_label(minutes: int) -> str:
    hours, rem = divmod(minutes, 60)
    if hours and rem:
        return f"{hours}h {rem}m"
    if hours:
        return f"{hours}h"
    return f"{rem}m"


@dataclass(frozen=True, slots=True)
class AddWorkLogInput:
    ticket_key: str
    time_spent_minutes: int
    started_at: datetime | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class UpdateWorkLogInput:
    ticket_key: str
    work_log_id: int
    time_spent_minutes: int | None = None
    started_at: datetime | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteWorkLogInput:
    ticket_key: str
    work_log_id: int


def add_work_log(command: AddWorkLogInput, *, actor: Any) -> TicketWorkLog:
    """Log effort on a support ticket and append an audit activity record."""
    ticket = get_ticket_for_actor(command.ticket_key, actor)
    if not can_log_work(actor, ticket):
        raise PermissionDeniedError("You do not have permission to log work on this ticket.")

    _validate_minutes(command.time_spent_minutes)
    now = timezone.now()
    started = command.started_at or now
    desc = command.description.strip()

    with transaction.atomic():
        work_log = TicketWorkLog.objects.create(
            ticket=ticket,
            author=actor,
            time_spent_minutes=command.time_spent_minutes,
            started_at=started,
            description=desc,
        )
        SupportTicket.objects.filter(pk=ticket.pk).update(last_activity_at=now)
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.WORK_LOGGED.value,
            actor=actor,
            actor_name=actor_display_name(actor),
            payload={
                "work_log_id": work_log.pk,
                "time_spent_minutes": work_log.time_spent_minutes,
                "duration": _format_minutes_label(work_log.time_spent_minutes),
                "description": desc[:200],
            },
        )
    return work_log


def update_work_log(command: UpdateWorkLogInput, *, actor: Any) -> TicketWorkLog:
    """Update an existing work log entry."""
    ticket = get_ticket_for_actor(command.ticket_key, actor)
    work_log = (
        TicketWorkLog.objects.select_related("author", "ticket")
        .filter(pk=command.work_log_id, ticket=ticket)
        .first()
    )
    if not work_log:
        raise RecordNotFoundError(f"Work log {command.work_log_id} not found.")

    if not can_manage_work_log(actor, work_log):
        raise PermissionDeniedError("You do not have permission to modify this work log.")

    changes: dict[str, dict[str, Any]] = {}
    update_fields: list[str] = ["updated_at"]

    if command.time_spent_minutes is not None and command.time_spent_minutes != work_log.time_spent_minutes:
        _validate_minutes(command.time_spent_minutes)
        changes["time_spent"] = {
            "old": _format_minutes_label(work_log.time_spent_minutes),
            "new": _format_minutes_label(command.time_spent_minutes),
        }
        work_log.time_spent_minutes = command.time_spent_minutes
        update_fields.append("time_spent_minutes")

    if command.started_at is not None and command.started_at != work_log.started_at:
        work_log.started_at = command.started_at
        update_fields.append("started_at")

    if command.description is not None:
        cleaned = command.description.strip()
        if cleaned != work_log.description:
            changes["description"] = {"old": work_log.description[:100], "new": cleaned[:100]}
            work_log.description = cleaned
            update_fields.append("description")

    if len(update_fields) == 1:
        return work_log

    now = timezone.now()
    with transaction.atomic():
        work_log.save(update_fields=update_fields)
        SupportTicket.objects.filter(pk=ticket.pk).update(last_activity_at=now)
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.WORK_LOG_UPDATED.value,
            actor=actor,
            actor_name=actor_display_name(actor),
            payload={
                "work_log_id": work_log.pk,
                "time_spent_minutes": work_log.time_spent_minutes,
                "duration": _format_minutes_label(work_log.time_spent_minutes),
                "changes": changes,
            },
        )
    return work_log


def delete_work_log(command: DeleteWorkLogInput, *, actor: Any) -> None:
    """Delete an existing work log entry and log the removal."""
    ticket = get_ticket_for_actor(command.ticket_key, actor)
    work_log = (
        TicketWorkLog.objects.select_related("author", "ticket")
        .filter(pk=command.work_log_id, ticket=ticket)
        .first()
    )
    if not work_log:
        raise RecordNotFoundError(f"Work log {command.work_log_id} not found.")

    if not can_manage_work_log(actor, work_log):
        raise PermissionDeniedError("You do not have permission to delete this work log.")

    now = timezone.now()
    with transaction.atomic():
        minutes = work_log.time_spent_minutes
        work_log_id = work_log.pk
        work_log.delete()
        SupportTicket.objects.filter(pk=ticket.pk).update(last_activity_at=now)
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.WORK_LOG_DELETED.value,
            actor=actor,
            actor_name=actor_display_name(actor),
            payload={
                "work_log_id": work_log_id,
                "time_spent_minutes": minutes,
                "duration": _format_minutes_label(minutes),
            },
        )
