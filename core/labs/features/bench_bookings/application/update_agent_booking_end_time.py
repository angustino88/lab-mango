"""Update only the end time of an approved booking linked to an agent's equipment."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction

from core.agents.public import AgentEnrollmentConflict, require_active_agent_identity
from core.labs.features.bench_bookings.exceptions import BenchBookingConflict
from core.labs.features.bench_bookings.queries import conflicting_bench_bookings
from core.labs.features.equipment.public import lock_active_equipment_bench_assignment
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus

from . import policies
from .locks import lock_benches
from .notification_intents import record_notification


@dataclass(frozen=True, slots=True)
class AgentBookingEndTimeInput:
    booking_id: int
    agent_uid: UUID
    ends_at: datetime
    request_id: str


@transaction.atomic
def update_agent_booking_end_time(command: AgentBookingEndTimeInput, *, actor: object) -> BenchBooking:
    """Change an associated approved booking's end time; ``actor`` is never treated as a Django user.

    The identity is resolved only from the supplied active ``agent_uid``; this is a credential
    subject lookup, not API authentication. Equipment and its active bench binding are derived
    through owner feature boundaries. Lock order is identity, equipment, bench, booking;
    ``request_id`` is carried for future audit integration but not persisted and does not provide
    request-key idempotency.
    """
    try:
        identity = require_active_agent_identity(command.agent_uid, actor=actor)
    except AgentEnrollmentConflict as error:
        raise BenchBookingConflict("The booking is not associated with this agent's equipment.") from error
    assignment = lock_active_equipment_bench_assignment(equipment_id=identity.equipment_id)
    if assignment is None:
        raise BenchBookingConflict("The booking is not associated with this agent's equipment.")

    booking_bench_id = BenchBooking.objects.values_list("bench_id", flat=True).filter(pk=command.booking_id).first()
    if booking_bench_id is None:
        raise BenchBookingConflict("The booking is not associated with this agent's equipment.")

    benches = lock_benches((booking_bench_id,))
    booking = BenchBooking.objects.select_for_update().filter(pk=command.booking_id).first()
    if booking is None:
        raise BenchBookingConflict("The booking is not associated with this agent's equipment.")
    if booking.bench_id != booking_bench_id:
        raise BenchBookingConflict("The booking moved concurrently; retry the request.")

    if assignment.bench_id != booking.bench_id:
        raise BenchBookingConflict("The booking is not associated with this agent's equipment.")
    if booking.approval_status != BookingApprovalStatus.APPROVED or booking.status not in {
        BookingStatus.RESERVED,
        BookingStatus.IN_PROGRESS,
    }:
        raise BenchBookingConflict("Only approved reserved or in-progress bookings can change end time.")

    policies.ensure_bench_accepts_bookings(benches[booking.bench_id])
    policies.ensure_valid_period(booking.starts_at, command.ends_at)
    policies.ensure_minimum_duration(booking.starts_at, command.ends_at)
    if command.ends_at == booking.ends_at:
        return booking

    updated_approval_status = policies.approval_status_for_schedule_change(
        duration=command.ends_at - booking.starts_at,
        current_status=booking.approval_status,
    )

    conflicts = conflicting_bench_bookings(
        bench_id=booking.bench_id,
        starts_at=booking.starts_at,
        ends_at=command.ends_at,
        exclude_id=booking.pk,
    )
    policies.ensure_no_conflicting_bookings(has_conflicts=conflicts.exists())

    booking.ends_at = command.ends_at
    update_fields = ["ends_at", "modified"]
    if updated_approval_status != booking.approval_status:
        booking.approval_status = updated_approval_status
        booking.approved_by = None
        booking.approved_at = None
        update_fields.extend(("approval_status", "approved_by", "approved_at"))
    booking.save(update_fields=update_fields)
    record_notification(booking=booking, kind="updated")
    return booking
