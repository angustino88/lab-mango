"""Release equipment from its active bench assignment."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.labs.models import Equipment
from core.labs.models.resource.equipment.assignment import EquipmentAssignment


@dataclass(frozen=True, slots=True)
class UnassignEquipmentInput:
    equipment_id: int


@transaction.atomic
def unassign_equipment(command: UnassignEquipmentInput, *, actor):
    equipment = Equipment.objects.select_for_update().get(id=command.equipment_id, deleted_at__isnull=True)
    assignment = EquipmentAssignment.objects.select_for_update().filter(
        equipment=equipment, unassigned_at__isnull=True
    ).first()
    if assignment is None:
        return None
    assignment.unassigned_at = timezone.now()
    assignment.last_modified_by = actor
    assignment.save(update_fields=("unassigned_at", "last_modified_by"))
    return assignment
