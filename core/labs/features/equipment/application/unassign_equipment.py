"""Release equipment from its active bench assignment."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.labs.features.equipment.application._status_transition import record_equipment_status
from core.labs.models import Equipment, EquipmentStatus
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
    record_equipment_status(
        equipment=equipment,
        status=EquipmentStatus.AVAILABLE,
        details={"bench": assignment.bench_id, "bench_id": assignment.bench_id},
        actor=actor,
    )
    return assignment
