"""Lock the booking an agent names by code, together with what proves it belongs to that agent."""

from dataclasses import dataclass
from uuid import UUID

from core.agents.public import AgentEnrollmentConflict, require_active_agent_identity
from core.labs.features.equipment.public import lock_active_equipment_bench_assignment
from core.labs.models import Bench, BenchBooking

from .locks import lock_benches


@dataclass(frozen=True, slots=True)
class LockedAgentBooking:
    booking: BenchBooking
    bench: Bench
    computer_bench_id: int


def lock_agent_booking(*, agent_uid: UUID, booking_code: str, actor: object) -> LockedAgentBooking | None:
    """Lock and return the booking with this code on the agent's own bench, or None.

    Lock order is identity, equipment, bench, booking, as in ``update_agent_booking_end_time``. The
    equipment lock keeps the computer's bench placement stable, the bench lock serialises with every
    other booking writer on that bench, and the booking row lock serialises agent actions on it.
    Must run inside the caller's transaction. Every reason for refusal returns the same None.
    """
    code = booking_code.strip()
    if not code:
        return None
    try:
        identity = require_active_agent_identity(agent_uid, actor=actor)
    except AgentEnrollmentConflict:
        return None
    placement = lock_active_equipment_bench_assignment(equipment_id=identity.equipment_id)
    if placement is None:
        return None
    booking_bench_id = BenchBooking.objects.filter(booking_code=code).values_list("bench_id", flat=True).first()
    if booking_bench_id is None or booking_bench_id != placement.bench_id:
        return None
    bench = lock_benches((booking_bench_id,))[booking_bench_id]
    booking = (
        BenchBooking.objects.select_for_update(of=("self",))
        .select_related("requester", "creator")
        .filter(booking_code=code, bench_id=booking_bench_id)
        .first()
    )
    if booking is None:  # moved to another bench between the read and the lock
        return None
    return LockedAgentBooking(booking=booking, bench=bench, computer_bench_id=placement.bench_id)
