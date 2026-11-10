"""Update a bench booking under bench and booking row locks."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.common.api.permissions import is_owner
from core.labs.features.bench_bookings.exceptions import BenchBookingConflict, BenchBookingPermissionDenied
from core.labs.features.bench_bookings.queries import conflicting_bench_bookings, project_exists
from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus, ensure_booking_status_transition
from core.users.public import LabsRole, has_labs_role

from . import policies
from .locks import lock_benches
from .notification_intents import material_values, record_notification

WRITABLE_FIELDS = frozenset(
    {"bench_id", "starts_at", "ends_at", "reason", "project_id", "status", "cancellation_reason"}
)
TERMINAL_STATUSES = frozenset({BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.EXPIRED})
DEFAULT_CANCELLATION_REASON = "Cancelled by user"


@dataclass(frozen=True, slots=True)
class UpdateBenchBookingInput:
    booking_id: int
    fields: Mapping[str, Any]


def _ensure_can_modify(actor, booking: BenchBooking) -> None:
    """Edits, cancels and completions are allowed for the owner and for lab coordinators and admins."""
    if is_owner(actor, booking) or has_labs_role(actor, LabsRole.COORDINATOR):
        return
    raise BenchBookingPermissionDenied(
        "Only the booking owner, a lab coordinator, or a lab administrator can change this booking."
    )


def update_bench_booking(*, actor, data: UpdateBenchBookingInput) -> BenchBooking:
    unknown = set(data.fields) - WRITABLE_FIELDS
    if unknown:
        raise ValidationError({name: "This field is not writable." for name in unknown})

    with transaction.atomic():
        current_bench_id = BenchBooking.objects.values_list("bench_id", flat=True).get(pk=data.booking_id)
        target_bench_id = data.fields.get("bench_id", current_bench_id)
        benches = lock_benches((current_bench_id, target_bench_id))

        booking = BenchBooking.objects.select_for_update().get(pk=data.booking_id)
        if booking.bench_id != current_bench_id:
            raise BenchBookingConflict("The booking moved concurrently; reload it and retry.")
        _ensure_can_modify(actor, booking)
        cancelling = data.fields.get("status") == BookingStatus.CANCELLED
        if (
            cancelling
            and booking.status == BookingStatus.CANCELLED
            and set(data.fields) <= {"status", "cancellation_reason"}
        ):
            # A retried cancel is a no-op; the first cancellation reason is kept.
            return booking
        if booking.approval_status == BookingApprovalStatus.REJECTED and not cancelling:
            # A rejection is a coordinator decision; editing must not re-queue the booking.
            raise BenchBookingConflict("A rejected booking can only be cancelled.")
        if "cancellation_reason" in data.fields and not cancelling:
            raise ValidationError({"cancellation_reason": "A cancellation reason is accepted only when cancelling."})
        cancelling_reserved_booking = booking.status == BookingStatus.RESERVED and cancelling
        if (
            booking.status == BookingStatus.RESERVED
            and not cancelling_reserved_booking
            and booking.starts_at + policies.ACTIVATION_WINDOW <= timezone.now()
        ):
            raise BenchBookingConflict("This booking has expired and cannot be updated.")
        before = material_values(booking)

        bench_changed = target_bench_id != current_bench_id
        starts_changed = "starts_at" in data.fields and data.fields["starts_at"] != booking.starts_at
        ends_changed = "ends_at" in data.fields and data.fields["ends_at"] != booking.ends_at
        status_changed = "status" in data.fields and data.fields["status"] != booking.status
        policies.ensure_start_mutable(
            booking.status,
            starts_at_changed=starts_changed,
            bench_changed=bench_changed,
        )
        if status_changed:
            if data.fields["status"] in {BookingStatus.EXPIRED, BookingStatus.IN_PROGRESS}:
                status_label = BookingStatus(data.fields["status"]).label.lower()
                raise ValidationError({"status": f"{status_label.capitalize()} status is managed automatically."})
            ensure_booking_status_transition(
                current_status=booking.status,
                target_status=data.fields["status"],
            )
        if booking.status in TERMINAL_STATUSES:
            # History is immutable: a finished, cancelled or expired booking keeps its schedule.
            raise BenchBookingConflict(
                f"A {BookingStatus(booking.status).label.lower()} booking cannot be changed."
            )
        if bench_changed:
            policies.ensure_bench_accepts_bookings(benches[target_bench_id])

        for name, value in data.fields.items():
            setattr(booking, name, value)
        if status_changed and booking.status == BookingStatus.CANCELLED:
            booking.cancellation_reason = booking.cancellation_reason.strip() or DEFAULT_CANCELLATION_REASON

        policies.ensure_valid_period(booking.starts_at, booking.ends_at)
        policies.ensure_minimum_duration(booking.starts_at, booking.ends_at)
        if starts_changed or ends_changed:
            # Either edge can lengthen the booking past the approval threshold.
            updated_approval_status = policies.approval_status_for_schedule_change(
                duration=booking.ends_at - booking.starts_at,
                current_status=booking.approval_status,
            )
            if updated_approval_status != booking.approval_status:
                booking.approval_status = updated_approval_status
                if updated_approval_status == BookingApprovalStatus.PENDING:
                    booking.approved_by = None
                    booking.approved_at = None
        if starts_changed:
            policies.ensure_startable(booking.starts_at, now=timezone.now())
        if booking.project_id is not None:
            policies.ensure_project_exists(exists=project_exists(project_id=booking.project_id))
        if bench_changed or starts_changed or ends_changed:
            conflicts = conflicting_bench_bookings(
                bench_id=booking.bench_id,
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                exclude_id=booking.pk,
            )
            policies.ensure_no_conflicting_bookings(has_conflicts=conflicts.exists())
        booking.save(actor=actor)
        if before != material_values(booking):
            record_notification(booking=booking, kind="updated")
    return booking
