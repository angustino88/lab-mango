"""Extend a running booking at the user's request from the agent (owner decision O28)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.labs.features.bench_bookings.contracts import AgentBookingExtended
from core.labs.features.bench_bookings.exceptions import AgentExtensionBenchNotFree, AgentExtensionNotAllowed
from core.labs.features.bench_bookings.queries import conflicting_bench_bookings
from core.labs.models import BookingApprovalStatus, BookingStatus

from . import policies
from .agent_booking_locks import lock_agent_booking
from .notification_intents import record_notification


@dataclass(frozen=True, slots=True)
class ExtendAgentBookingInput:
    """``agent_uid`` is the signing agent; the computer and bench are derived from it, never the body."""

    agent_uid: UUID
    booking_code: str
    ends_at: datetime


@transaction.atomic
def extend_agent_booking(
    command: ExtendAgentBookingInput, *, actor: object, now: datetime | None = None
) -> AgentBookingExtended | None:
    """Move the end of an approved in-progress booking on the agent's bench later.

    Returns None, with no detail, when the code is unknown, on another bench, not approved or not in
    progress (E1). Raises ``AgentExtensionNotAllowed`` (E2, E3, E5, E6, bench out of service) or
    ``AgentExtensionBenchNotFree`` (E4) once the booking is proven to be the agent's. The new end is
    floored to the minute. Asking for the current end again returns it without a write (E7).

    Race guard: ``lock_agent_booking`` takes the bench lock that every booking writer takes before
    its overlap check, so a booking created at the same moment either sees the extension or blocks
    it. A change records an ``updated`` notification (E8).
    """
    now = now or timezone.now()
    new_ends_at = command.ends_at.replace(second=0, microsecond=0)
    locked = lock_agent_booking(agent_uid=command.agent_uid, booking_code=command.booking_code, actor=actor)
    if locked is None:
        return None
    booking = locked.booking
    if booking.approval_status != BookingApprovalStatus.APPROVED or booking.status != BookingStatus.IN_PROGRESS:
        return None
    if new_ends_at != booking.ends_at:
        policies.ensure_agent_extension(
            starts_at=booking.starts_at, current_ends_at=booking.ends_at, new_ends_at=new_ends_at, now=now
        )
        try:
            policies.ensure_bench_accepts_bookings(locked.bench)
        except ValidationError as error:
            raise AgentExtensionNotAllowed(
                reason="bench_not_in_service", message="The bench is not in service."
            ) from error
        next_start = (
            conflicting_bench_bookings(
                bench_id=booking.bench_id, starts_at=booking.ends_at, ends_at=new_ends_at, exclude_id=booking.pk
            )
            .order_by("starts_at")
            .values_list("starts_at", flat=True)
            .first()
        )
        if next_start is not None:
            raise AgentExtensionBenchNotFree(available_until=next_start)
        booking.ends_at = new_ends_at
        booking.save(update_fields=("ends_at", "modified"))
        record_notification(booking=booking, kind="updated")
    return AgentBookingExtended(
        booking_code=booking.booking_code, starts_at=booking.starts_at, ends_at=booking.ends_at
    )
