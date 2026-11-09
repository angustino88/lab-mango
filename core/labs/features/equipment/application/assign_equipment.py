"""Assign equipment to a bench."""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.application._status_transition import record_equipment_status
from core.labs.features.equipment.exceptions import EquipmentAlreadyAssigned
from core.labs.models import Bench, Equipment, EquipmentStatus
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
        record_equipment_status(
            equipment=equipment,
            status=EquipmentStatus.IN_USE,
            details={"bench": command.bench_id, "bench_id": command.bench_id},
            actor=actor,
        )
        return current
    if current:
        raise EquipmentAlreadyAssigned()
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
    record_equipment_status(
        equipment=equipment,
        status=EquipmentStatus.IN_USE,
        details={"bench": command.bench_id, "bench_id": command.bench_id},
        actor=actor,
    )
    return assignment
