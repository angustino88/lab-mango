"""Delete an equipment item using the model's soft-delete behavior."""

from dataclasses import dataclass

from django.db import transaction

from core.labs.models import Booking, Equipment, EquipmentAssignment, EquipmentBooking, LicenseAssignment

from ..exceptions import EquipmentInUse
from ._validation import validate_equipment_model


@dataclass(frozen=True, slots=True)
class DeleteEquipmentInput:
    equipment_id: int
    model: type[Equipment]


@transaction.atomic
def delete_equipment(command: DeleteEquipmentInput, *, actor):
    """Lock and soft-delete one equipment model, refusing while live records point at it.

    Race guard: the ``Equipment`` row lock. ``assign_equipment`` and ``assign_license`` lock the
    same row first and only accept non-deleted equipment, so neither can add a dependent between
    the checks below and the soft delete. Equipment bookings have no application write path yet
    (Django admin only); the booking feature must lock ``Equipment`` first as well.
    Idempotency: deleting an already deleted unit raises ``DoesNotExist`` (404), as before.
    """
    validate_equipment_model(command.model)
    instance = command.model.objects.select_for_update().get(
        pk=command.equipment_id, deleted_at__isnull=True,
    )
    _ensure_no_live_dependents(instance.pk)
    instance.delete(actor=actor)
    return instance


def _ensure_no_live_dependents(equipment_id: int) -> None:
    blockers = []
    if EquipmentAssignment.objects.filter(equipment_id=equipment_id, unassigned_at__isnull=True).exists():
        blockers.append("bench_assignment")
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
            "Unassign the bench, release license seats, and cancel active bookings before deleting.",
            details={"blockers": blockers},
        )


__all__ = ("DeleteEquipmentInput", "delete_equipment")
