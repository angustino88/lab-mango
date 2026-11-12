"""Read-only check an agent makes before logging a user in with a booking code."""

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from core.labs.features.bench_bookings.contracts import AgentBookingLogin
from core.labs.features.bench_bookings.queries import find_bench_booking_for_agent_login
from core.labs.features.equipment.public import active_equipment_bench_assignment

from . import policies


@dataclass(frozen=True)
class CheckAgentBookingLoginInput:
    """``equipment_id`` is the signing agent's computer, never a value from the request body."""

    equipment_id: int
    booking_code: str


def check_agent_booking_login(
    command: CheckAgentBookingLoginInput, *, now: datetime | None = None
) -> AgentBookingLogin | None:
    """Return the booking when the agent may log a user in with it now, otherwise None.

    Read-only: no transaction, lock, check-in or status change. Every failure returns the same
    None so the caller cannot learn whether a code exists or which bench it belongs to.
    Two queries: the booking (with its users) and the computer's active bench.
    """
    now = now or timezone.now()
    booking_code = command.booking_code.strip()
    if not booking_code:
        return None
    booking = find_bench_booking_for_agent_login(booking_code=booking_code)
    if booking is None:
        return None
    placement = active_equipment_bench_assignment(equipment_id=command.equipment_id)
    eligible = policies.is_agent_login_eligible(
        status=booking.status,
        approval_status=booking.approval_status,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        booking_bench_id=booking.bench_id,
        computer_bench_id=placement.bench_id if placement is not None else None,
        now=now,
    )
    if not eligible:
        return None
    booked_for = booking.requester or booking.creator
    return AgentBookingLogin(
        booking_code=booking.booking_code,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        booked_for=booked_for.get_username() if booked_for is not None else None,
    )
