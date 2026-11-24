"""Add, update, and delete ticket work log (effort tracking) use cases."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone
from django.utils.http import parse_etags

from core.common.domain.errors import Conflict, ValidationFailed
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
from core.support_desk.models.work_log import (
    MAX_WORK_LOG_MINUTES,
    MIN_WORK_LOG_MINUTES,
    TicketWorkLog,
    TicketWorkLogCreateReceipt,
)


def _validate_minutes(minutes: int) -> None:
    if type(minutes) is not int or not MIN_WORK_LOG_MINUTES <= minutes <= MAX_WORK_LOG_MINUTES:
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
    if_match: str | None
    time_spent_minutes: int | None = None
    started_at: datetime | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteWorkLogInput:
    ticket_key: str
    work_log_id: int
    if_match: str | None


class WorkLogPreconditionRequired(Conflict):
    code = "precondition_required"
    status_code = 428


class WorkLogPreconditionFailed(Conflict):
    code = "precondition_failed"
    status_code = 412


def _require_match(if_match: str | None, work_log: TicketWorkLog) -> None:
    if if_match is None:
        raise WorkLogPreconditionRequired("If-Match is required to change a work log.")
    tags = parse_etags(if_match)
    if tags != ["*"] and work_log.etag not in tags:
        raise WorkLogPreconditionFailed("This work log has changed. Reload it and try again.")


def add_work_log(
    command: AddWorkLogInput,
    *,
    actor: Any,
    idempotency_key: UUID,
    project_response: Callable[[TicketWorkLog], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Log effort once per request key and append an audit activity record."""
    _validate_minutes(command.time_spent_minutes)
    desc = command.description.strip()
    request_values = [command.time_spent_minutes, command.started_at.isoformat() if command.started_at else None, desc]
    request_hash = hashlib.sha256(json.dumps(request_values).encode()).hexdigest()
    scope = f"ticket-work-log:{actor.pk}:{idempotency_key}"
    lock_id = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [lock_id])
            if not cursor.fetchone()[0]:
                raise Conflict("This request is still running.", code="request_in_progress")

        # All work-log writers lock the ticket first, serializing edits and activity updates.
        ticket = get_ticket_for_actor(command.ticket_key, actor, lock=True)
        if not can_log_work(actor, ticket):
            raise PermissionDeniedError("You do not have permission to log work on this ticket.")

        now = timezone.now()
        receipts = TicketWorkLogCreateReceipt.objects.filter(actor=actor, key=idempotency_key)
        receipts.filter(expires_at__lte=now).delete()
        receipt = receipts.first()
        if receipt is not None:
            if receipt.ticket_id != ticket.pk or receipt.request_hash != request_hash:
                raise ValidationFailed(
                    "Idempotency-Key was already used with a different ticket or input.", code="idempotency_key_reuse"
                )
            return receipt.response_body, True

        work_log = TicketWorkLog.objects.create(
            ticket=ticket,
            author=actor,
            time_spent_minutes=command.time_spent_minutes,
            started_at=command.started_at or now,
            description=desc,
        )
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
        response_body = project_response(work_log)
        receipts.create(
            ticket=ticket,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            response_body=response_body,
            expires_at=now + timedelta(hours=24),
        )
        return response_body, False


@transaction.atomic
def update_work_log(command: UpdateWorkLogInput, *, actor: Any) -> TicketWorkLog:
    """Update an existing work log entry."""
    ticket = get_ticket_for_actor(command.ticket_key, actor, lock=True)
    work_log = (
        TicketWorkLog.objects.select_related("author", "ticket").filter(pk=command.work_log_id, ticket=ticket).first()
    )
    if not work_log:
        raise RecordNotFoundError(f"Work log {command.work_log_id} not found.")

    if not can_manage_work_log(actor, work_log):
        raise PermissionDeniedError("You do not have permission to modify this work log.")

    _require_match(command.if_match, work_log)

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
        changes["started_at"] = {"old": work_log.started_at.isoformat(), "new": command.started_at.isoformat()}
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

    work_log.version += 1
    work_log.save(update_fields=[*update_fields, "version"])
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


@transaction.atomic
def delete_work_log(command: DeleteWorkLogInput, *, actor: Any) -> None:
    """Delete an existing work log entry and log the removal."""
    ticket = get_ticket_for_actor(command.ticket_key, actor, lock=True)
    work_log = (
        TicketWorkLog.objects.select_related("author", "ticket").filter(pk=command.work_log_id, ticket=ticket).first()
    )
    if not work_log:
        raise RecordNotFoundError(f"Work log {command.work_log_id} not found.")

    if not can_manage_work_log(actor, work_log):
        raise PermissionDeniedError("You do not have permission to delete this work log.")

    _require_match(command.if_match, work_log)

    minutes = work_log.time_spent_minutes
    work_log_id = work_log.pk
    work_log.delete()
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
