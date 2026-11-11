"""Check a user in with a booking code at the agent: the booking becomes in progress."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from core.labs.features.bench_bookings.contracts import AgentBookingLogin
from core.labs.models import BookingStatus
from core.labs.models.booking import ensure_booking_status_transition

from . import policies
from .agent_booking_locks import lock_agent_booking


@dataclass(frozen=True, slots=True)
class CheckInAgentBookingInput:
    """``agent_uid`` is the signing agent; the computer and bench are derived from it, never the body."""

    agent_uid: UUID
    booking_code: str


@transaction.atomic
def check_in_agent_booking(
    command: CheckInAgentBookingInput, *, actor: object, now: datetime | None = None
) -> AgentBookingLogin | None:
    """Check in with this code on the agent's computer, or return None when the booking is not usable.

    Eligibility is ``policies.is_agent_login_eligible``, the same rule as the read-only login check.
    A reserved booking moves to in progress; an in-progress booking is left as it is, so a user who
    logs out and back in checks in again without error. Every failure returns the same None.

    Race guard: ``lock_agent_booking`` (identity, equipment, bench, booking); the booking row lock
    makes two concurrent check-ins move the booking once. ``actor`` is the agent, never a Django user.
    No notification is recorded, matching ``activate_bench_bookings``.
    """
    now = now or timezone.now()
    locked = lock_agent_booking(agent_uid=command.agent_uid, booking_code=command.booking_code, actor=actor)
    if locked is None:
        return None
    booking = locked.booking

    eligible = policies.is_agent_login_eligible(
        status=booking.status,
        approval_status=booking.approval_status,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        booking_bench_id=booking.bench_id,
        computer_bench_id=locked.computer_bench_id,
        now=now,
    )
    if not eligible:
        return None
    if booking.status == BookingStatus.RESERVED:
        ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.IN_PROGRESS)
        booking.status = BookingStatus.IN_PROGRESS
        booking.save(update_fields=("status", "modified"))

    booked_for = booking.requester or booking.creator
    return AgentBookingLogin(
        booking_code=booking.booking_code,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        booked_for=booked_for.get_username() if booked_for is not None else None,
    )
