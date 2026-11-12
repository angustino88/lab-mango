"""End a booking when the user chooses to at the agent: the booking becomes completed."""

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from core.labs.features.bench_bookings.contracts import AgentBookingEnded
from core.labs.models import BookingApprovalStatus, BookingStatus
from core.labs.models.booking import ensure_booking_status_transition

from .agent_booking_locks import lock_agent_booking
from .notification_intents import record_notification


@dataclass(frozen=True, slots=True)
class CompleteAgentBookingInput:
    """``agent_uid`` is the signing agent; the computer and bench are derived from it, never the body."""

    agent_uid: UUID
    booking_code: str


@transaction.atomic
def complete_agent_booking(command: CompleteAgentBookingInput, *, actor: object) -> AgentBookingEnded | None:
    """End an in-progress booking on the agent's bench at the user's request (owner decision O25).

    Only an approved booking that has started (``in_progress``) can be ended; a reserved booking was
    never checked in. An already completed booking returns success without a write, so a retry is
    safe. Every other case returns None. ``ends_at`` is kept: it records the booked time, and a
    completed booking no longer blocks the bench. Bookings nobody ends are completed at their end
    time by the scheduled reconciliation job (``labs.bench_bookings.reconcile_statuses``).

    Race guard: ``lock_agent_booking`` (identity, equipment, bench, booking). A status change records
    an ``updated`` notification, as ending through ``update_bench_booking`` does.
    """
    locked = lock_agent_booking(agent_uid=command.agent_uid, booking_code=command.booking_code, actor=actor)
    if locked is None:
        return None
    booking = locked.booking
    if booking.approval_status != BookingApprovalStatus.APPROVED:
        return None
    if booking.status == BookingStatus.IN_PROGRESS:
        ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.COMPLETED)
        booking.status = BookingStatus.COMPLETED
        booking.save(update_fields=("status", "modified"))
        record_notification(booking=booking, kind="updated")
    elif booking.status != BookingStatus.COMPLETED:
        return None
    return AgentBookingEnded(booking_code=booking.booking_code, starts_at=booking.starts_at, ends_at=booking.ends_at)
