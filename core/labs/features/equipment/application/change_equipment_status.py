"""Record an equipment status transition."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from core.labs.features.equipment.application._status_transition import record_equipment_status
from core.labs.models import Equipment


@dataclass(frozen=True, slots=True)
class ChangeEquipmentStatusInput:
    equipment_id: int
    status: str
    details: tuple[tuple[str, Any], ...] = ()


@transaction.atomic
def change_equipment_status(command: ChangeEquipmentStatusInput, *, actor):
    equipment = Equipment.objects.select_for_update().get(id=command.equipment_id, deleted_at__isnull=True)
    return record_equipment_status(
        equipment=equipment,
        status=command.status,
        details=dict(command.details),
        actor=actor,
    )
