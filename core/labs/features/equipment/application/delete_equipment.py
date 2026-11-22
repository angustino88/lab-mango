"""Delete an equipment item using the model's soft-delete behavior."""

from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.labs.features.licenses.public import UnassignLicenseInput, unassign_license
from core.labs.models import (
    Booking,
    Equipment,
    EquipmentAssignment,
    EquipmentBooking,
    EquipmentLoan,
    LicenseAssignment,
    LoanCloseReason,
    ResourceChangeLog,
)
from core.labs.models.booking.base import BookingStatus, ensure_booking_status_transition
from core.labs.models.resource.equipment.loan import CONDITION_NOTE_MAX_LENGTH

from ..exceptions import EquipmentInUse
from ._placement import close_placement, lock_active_loan, lock_active_placement

FORCE_DELETE_REASON_MIN_LENGTH = 3
FORCE_DELETE_REASON_MAX_LENGTH = 500


@dataclass(frozen=True, slots=True)
class DeleteEquipmentInput:
    equipment_id: int


@dataclass(frozen=True, slots=True)
class ForceDeleteEquipmentInput:
    equipment_id: int
    reason: str
    confirm: bool = True


@dataclass(frozen=True, slots=True)
class ForceDeleteReleasedSummary:
    bench_assignments: int = 0
    loans: int = 0
    license_assignments: int = 0
    bookings: int = 0


@dataclass(frozen=True, slots=True)
class ForceDeleteEquipmentResult:
    equipment: Equipment
    released: ForceDeleteReleasedSummary


@transaction.atomic
def delete_equipment(command: DeleteEquipmentInput, *, actor):
    """Lock and soft-delete one equipment model, refusing while live records point at it.

    Race guard: the ``Equipment`` row lock. ``assign_equipment`` and ``assign_license`` lock the
    same row first and only accept non-deleted equipment, so neither can add a dependent between
    the checks below and the soft delete. Equipment bookings have no application write path yet
    (Django admin only); the booking feature must lock ``Equipment`` first as well.
    Idempotency: deleting an already deleted unit raises ``DoesNotExist`` (404), as before.
    """
    instance = Equipment.objects.select_for_update().get(
        pk=command.equipment_id,
        deleted_at__isnull=True,
    )
    _ensure_no_live_dependents(instance.pk)
    # A unit resting at a station, in a room, or at an untracked place leaves it when deleted.
    resting = lock_active_placement(instance)
    if resting is not None:
        close_placement(resting, actor=actor)
    instance.delete(actor=actor)
    return instance


def force_delete_equipment(command: ForceDeleteEquipmentInput, *, actor) -> ForceDeleteEquipmentResult:
    """Release all live dependents atomically and soft-delete an equipment item.

    Race guard: locks ``Equipment`` first, then closes active placement, active loan, active
    license assignments (via ``licenses.public.unassign_license`` in ascending ``license_id``
    order to match ``assign_license``'s lock order), and active bookings (in ascending ``pk``
    order), all inside one transaction before soft-deleting the equipment row.
    Idempotency: calling again on an already-deleted unit raises ``Equipment.DoesNotExist`` (404).
    """
    if command.confirm is not True:
        raise ValidationError({"confirm": "Explicit confirmation is required to force-delete equipment."})
    reason = (command.reason or "").strip()
    if len(reason) < FORCE_DELETE_REASON_MIN_LENGTH:
        raise ValidationError({"reason": f"Provide a reason of at least {FORCE_DELETE_REASON_MIN_LENGTH} characters."})
    if len(reason) > FORCE_DELETE_REASON_MAX_LENGTH:
        raise ValidationError({"reason": f"Use at most {FORCE_DELETE_REASON_MAX_LENGTH} characters."})
    return _force_delete_equipment_tx(command.equipment_id, reason=reason, actor=actor)


@transaction.atomic
def _force_delete_equipment_tx(equipment_id: int, *, reason: str, actor) -> ForceDeleteEquipmentResult:
    instance = Equipment.objects.select_for_update().get(
        pk=equipment_id,
        deleted_at__isnull=True,
    )
    now = timezone.now()
    acting_user = actor if getattr(actor, "is_authenticated", False) else None

    # 1. Close any active placement (bench, station, room, or untracked note).
    placement = lock_active_placement(instance)
    bench_released = 1 if (placement is not None and placement.bench_id is not None) else 0
    if placement is not None:
        close_placement(placement, actor=actor)

    # 2. Close any active loan.
    loan = lock_active_loan(instance)
    loans_released = 0
    if loan is not None:
        loan.returned_at = now
        loan.received_by = acting_user
        loan.condition_in = f"Force-deleted: {reason}"[:CONDITION_NOTE_MAX_LENGTH]
        loan.close_reason = LoanCloseReason.RETURNED
        loan.save(update_fields=("returned_at", "received_by", "condition_in", "close_reason", "modified"))
        loans_released = 1

    # 3. Release any active license seats in ascending license_id order (Equipment -> License lock order).
    active_license_ids = list(
        LicenseAssignment.objects.filter(equipment_id=instance.pk, unassigned_at__isnull=True)
        .order_by("license_id")
        .values_list("license_id", flat=True)
        .distinct()
    )
    for license_id in active_license_ids:
        unassign_license(UnassignLicenseInput(equipment_id=instance.pk, license_id=license_id), actor=actor)

    # 4. Cancel any active reserving bookings in ascending pk order.
    active_bookings = list(
        EquipmentBooking.objects.select_for_update()
        .filter(
            equipment_id=instance.pk,
            status__in=Booking.ACTIVE_STATUSES,
            approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        )
        .order_by("pk")
    )
    cancellation_reason = f"Equipment force-deleted: {reason}"
    for booking in active_bookings:
        ensure_booking_status_transition(current_status=booking.status, target_status=BookingStatus.CANCELLED)
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = cancellation_reason
        booking.save(update_fields=("status", "cancellation_reason", "modified"))

    released = ForceDeleteReleasedSummary(
        bench_assignments=bench_released,
        loans=loans_released,
        license_assignments=len(active_license_ids),
        bookings=len(active_bookings),
    )

    # 5. Record audit entry when an authenticated actor performs the force delete.
    if acting_user is not None:
        content_type = ContentType.objects.get_for_model(instance, for_concrete_model=False)
        ResourceChangeLog(
            resource_content_type=content_type,
            resource_object_id=str(instance.pk),
            action=ResourceChangeLog.Action.DELETE,
            field_name="force_delete",
            old_value=None,
            new_value={
                "reason": reason,
                "released": {
                    "bench_assignments": released.bench_assignments,
                    "loans": released.loans,
                    "license_assignments": released.license_assignments,
                    "bookings": released.bookings,
                },
            },
        ).save(actor=acting_user)

    # 6. Soft-delete the equipment row.
    instance.delete(actor=actor)
    return ForceDeleteEquipmentResult(equipment=instance, released=released)


def _ensure_no_live_dependents(equipment_id: int) -> None:
    blockers = []
    if EquipmentAssignment.objects.filter(equipment_id=equipment_id, unassigned_at__isnull=True).exists():
        blockers.append("bench_assignment")
    if EquipmentLoan.objects.filter(equipment_id=equipment_id, returned_at__isnull=True).exists():
        blockers.append("loan")
    if LicenseAssignment.objects.filter(equipment_id=equipment_id, unassigned_at__isnull=True).exists():
        blockers.append("license_assignment")
    if EquipmentBooking.objects.filter(
        equipment_id=equipment_id,
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
    ).exists():
        blockers.append("booking")
    if blockers:
        raise EquipmentInUse(
            "Unassign the bench, take back a loan, release license seats, and cancel active bookings before deleting.",
            details={"blockers": blockers},
        )


__all__ = (
    "DeleteEquipmentInput",
    "ForceDeleteEquipmentInput",
    "ForceDeleteEquipmentResult",
    "ForceDeleteReleasedSummary",
    "delete_equipment",
    "force_delete_equipment",
)
