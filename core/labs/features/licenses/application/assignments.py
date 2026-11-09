"""Commands for assigning and releasing licenses on equipment."""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.licenses.exceptions import LicenseAlreadyAssigned
from core.labs.models import Equipment, License, LicenseAssignment


@dataclass(frozen=True)
class AssignLicenseInput:
    equipment_id: int
    license_id: int


@dataclass(frozen=True)
class UnassignLicenseInput:
    equipment_id: int
    license_id: int


@transaction.atomic
def assign_license(command: AssignLicenseInput, *, actor):
    equipment = Equipment.objects.select_for_update().get(id=command.equipment_id, deleted_at__isnull=True)
    license_record = License.objects.select_for_update().get(id=command.license_id, deleted_at__isnull=True)
    assignment = LicenseAssignment.objects.select_for_update().filter(
        equipment=equipment,
        license=license_record,
        unassigned_at__isnull=True,
    ).first()
    if assignment:
        return assignment
    try:
        with transaction.atomic():
            assignment = LicenseAssignment(
                equipment=equipment,
                license=license_record,
                creator=actor,
                last_modified_by=actor,
            )
            assignment.save(actor=actor)
        return assignment
    except IntegrityError as exc:
        assignment = LicenseAssignment.objects.filter(
            equipment=equipment,
            license=license_record,
            unassigned_at__isnull=True,
        ).first()
        if assignment is not None:
            return assignment
        raise LicenseAlreadyAssigned() from exc


@transaction.atomic
def unassign_license(command: UnassignLicenseInput, *, actor):
    assignment = LicenseAssignment.objects.select_for_update().filter(
        equipment_id=command.equipment_id,
        license_id=command.license_id,
        unassigned_at__isnull=True,
    ).first()
    if assignment is None:
        return None
    assignment.unassigned_at = timezone.now()
    assignment.last_modified_by = actor
    assignment.save(actor=actor, update_fields=("unassigned_at", "last_modified_by"))
    return assignment


__all__ = ["AssignLicenseInput", "UnassignLicenseInput", "assign_license", "unassign_license"]
