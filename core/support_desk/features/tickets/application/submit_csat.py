"""Customer satisfaction (CSAT) rating for resolved tickets."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType, SystemState
from core.support_desk.exceptions import CsatNotAllowedError, InvalidFieldValueError, PermissionDeniedError
from core.support_desk.features.tickets.application.policies import can_submit_csat
from core.support_desk.features.tickets.application.shared import actor_display_name, get_ticket_for_actor
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.settings import SupportSettings


@dataclass(frozen=True, slots=True)
class SubmitCsatInput:
    ticket_key: str
    score: int
    comment: str = ""


def submit_csat(command: SubmitCsatInput, *, actor: Any):
    """Let the requester rate a resolved ticket 1-5 (can be amended inside the CSAT window)."""
    ticket = get_ticket_for_actor(command.ticket_key, actor, select_related=("status",))
    if not can_submit_csat(actor, ticket):
        raise PermissionDeniedError("Only the requester can rate this ticket.")
    if not 1 <= command.score <= 5:
        raise InvalidFieldValueError("Satisfaction score must be between 1 and 5.")

    app_settings = SupportSettings.get_solo()
    if not app_settings.csat_enabled:
        raise CsatNotAllowedError("Satisfaction ratings are disabled.")
    if ticket.status.system_state != SystemState.DONE.value:
        raise CsatNotAllowedError("Only resolved tickets can be rated.")
    resolved_at = ticket.resolved_at or ticket.closed_at or ticket.updated_at
    if timezone.now() > resolved_at + timedelta(days=app_settings.csat_window_days):
        raise CsatNotAllowedError("The window to rate this ticket has expired.")

    now = timezone.now()
    with transaction.atomic():
        ticket.csat_score = command.score
        ticket.csat_comment = command.comment
        ticket.csat_submitted_at = now
        ticket.save(update_fields=["csat_score", "csat_comment", "csat_submitted_at", "updated_at"])
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.CSAT_SUBMITTED.value,
            actor=actor,
            actor_name=actor_display_name(actor),
            payload={"score": command.score, "comment": command.comment},
        )
    return ticket
