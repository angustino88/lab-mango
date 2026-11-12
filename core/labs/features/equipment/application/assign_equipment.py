"""Assign equipment to a bench."""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.application._placement import close_resting_placement, ensure_not_on_loan
from core.labs.features.equipment.exceptions import EquipmentAlreadyAssigned, InvalidEquipmentStatus
from core.labs.models import Bench, Equipment, EquipmentLifecycleState
from core.labs.models.resource.equipment.assignment import EquipmentAssignment


@dataclass(frozen=True, slots=True)
class AssignEquipmentInput:
    equipment_id: int
    bench_id: int
    role: str = "default"
    position: int = 0


@transaction.atomic
def assign_equipment(command: AssignEquipmentInput, *, actor):
    equipment = Equipment.objects.select_for_update().get(id=command.equipment_id, deleted_at__isnull=True)
    bench = Bench.objects.select_for_update().get(id=command.bench_id, deleted_at__isnull=True)
    current = EquipmentAssignment.objects.select_for_update().filter(
        equipment=equipment, unassigned_at__isnull=True
    ).first()
    if current and current.bench_id == command.bench_id:
        return current
    if equipment.lifecycle_state != EquipmentLifecycleState.IN_SERVICE:
        raise InvalidEquipmentStatus("Only equipment in service can be placed on a bench.")
    if not equipment.kind.category.placeable_on_bench:
        raise InvalidEquipmentStatus("Units of this category are not placed on a bench.")
    ensure_not_on_loan(equipment)
    if current:
        raise EquipmentAlreadyAssigned()
    # A unit resting at a station, in a room, or at an untracked place moves onto the bench.
    close_resting_placement(equipment, actor=actor)
    try:
        with transaction.atomic():
            assignment = EquipmentAssignment.objects.create(
                equipment=equipment,
                bench=bench,
                role=command.role,
                position=command.position,
                assigned_at=timezone.now(),
                creator=actor,
                last_modified_by=actor,
            )
    except IntegrityError as exc:
        cause = exc.__cause__ or exc
        constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
        if constraint_name == "one_active_bench_per_equipment":
            raise EquipmentAlreadyAssigned() from exc
        raise
    return assignment
