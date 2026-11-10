"""Equipment-owned status and category aggregates, without commercial data."""

from typing import Any

from django.db.models import Model

from core.common.queries.status_summary import status_summary
from core.labs.models import ComputingEquipment, Equipment, EquipmentDisplayStatus
from core.labs.models.activity.computing_activity import ComputingActivityStatus

from .equipment import with_display_status


def get_equipment_status_summary() -> dict[str, Any]:
    """Non-deleted equipment counted once each by computed ``display_status``. One query."""
    inventory = with_display_status(Equipment.objects.filter(deleted_at__isnull=True))
    return status_summary(inventory, field="display_status", choices=EquipmentDisplayStatus.choices)


def get_computing_activity_summary() -> dict[str, Any]:
    """Missing telemetry is unknown, not inferred offline; no user information."""
    return status_summary(
        ComputingEquipment.objects.filter(deleted_at__isnull=True),
        field="activity__status",
        choices=ComputingActivityStatus.choices,
    )


def get_equipment_category_status_summary(*, equipment_model: type[Model]) -> dict[str, Any]:
    """Count one registered equipment category by computed ``display_status``. One query."""
    inventory = with_display_status(equipment_model.objects.filter(deleted_at__isnull=True))
    return status_summary(inventory, field="display_status", choices=EquipmentDisplayStatus.choices)
