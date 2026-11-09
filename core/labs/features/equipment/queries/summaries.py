"""Equipment-owned status and category aggregates, without commercial data."""

from typing import Any

from django.db.models import Model

from core.common.queries.status_summary import status_summary, with_latest_status
from core.labs.models import ComputingEquipment, Equipment, EquipmentStatus, EquipmentStatusRecord
from core.labs.models.activity.computing_activity import ComputingActivityStatus


def get_equipment_status_summary() -> dict[str, Any]:
    inventory = with_latest_status(
        Equipment.objects.filter(deleted_at__isnull=True),
        records=EquipmentStatusRecord.objects.all(),
        resource_field="equipment_id",
    )
    return status_summary(inventory, field="summary_status", choices=EquipmentStatus.choices)


def get_computing_activity_summary() -> dict[str, Any]:
    """Missing telemetry is unknown, not inferred offline; no user information."""
    return status_summary(
        ComputingEquipment.objects.filter(deleted_at__isnull=True),
        field="activity__status",
        choices=ComputingActivityStatus.choices,
    )


def get_equipment_category_status_summary(*, equipment_model: type[Model]) -> dict[str, Any]:
    """Count one registered equipment category by its latest lifecycle state."""
    inventory = with_latest_status(
        equipment_model.objects.filter(deleted_at__isnull=True),
        records=EquipmentStatusRecord.objects.all(),
        resource_field="equipment_id",
    )
    return status_summary(inventory, field="summary_status", choices=EquipmentStatus.choices)
