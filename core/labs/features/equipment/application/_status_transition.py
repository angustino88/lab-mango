"""Private persistence primitive shared by equipment status commands."""

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.equipment.application._placement import close_resting_placement
from core.labs.features.equipment.exceptions import InvalidEquipmentStatus
from core.labs.models import Bench, Equipment, EquipmentStatus, EquipmentStatusRecord
from core.labs.models.resource.equipment.assignment import EquipmentAssignment


def record_equipment_status(*, equipment: Equipment, status: str, details: dict[str, Any], actor):
    if status not in EquipmentStatus.values:
        raise InvalidEquipmentStatus(f"Unsupported equipment status: {status}.")
    metadata = details or {}
    bench_id = metadata.get("bench", metadata.get("bench_id"))
    active_assignment = EquipmentAssignment.objects.select_for_update().filter(
        equipment=equipment, unassigned_at__isnull=True
    ).first()

    if status == EquipmentStatus.IN_USE:
        if bench_id is None:
            raise InvalidEquipmentStatus("in_use requires a bench")
        bench = Bench.objects.select_for_update().get(id=bench_id, deleted_at__isnull=True)
        metadata = {**metadata, "bench": bench.pk, "bench_id": bench.pk}
        if active_assignment is None:
            close_resting_placement(equipment, actor=actor)
            try:
                with transaction.atomic():
                    EquipmentAssignment.objects.create(
                        equipment=equipment,
                        bench=bench,
                        assigned_at=timezone.now(),
                        creator=actor,
                        last_modified_by=actor,
                    )
            except IntegrityError as exc:
                cause = exc.__cause__ or exc
                constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
                if constraint_name == "one_active_bench_per_equipment":
                    raise InvalidEquipmentStatus("equipment is already assigned to a bench") from exc
                raise
        elif active_assignment.bench_id != bench.pk:
            raise InvalidEquipmentStatus("equipment is already assigned to another bench")
    elif active_assignment is not None:
        active_assignment.unassigned_at = timezone.now()
        active_assignment.last_modified_by = actor
        active_assignment.save(update_fields=("unassigned_at", "last_modified_by"))

    latest = equipment.status_records.order_by("-created", "-id").first()
    if latest and latest.status == status and latest.metadata == metadata:
        return latest
    return EquipmentStatusRecord.objects.create(
        equipment=equipment,
        status=status,
        metadata=metadata,
        creator=actor,
        last_modified_by=actor,
    )
