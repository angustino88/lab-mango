"""Equipment-owned status and category aggregates, without commercial data."""

from typing import Any

from core.common.queries.status_summary import status_summary
from core.labs.models import Equipment, EquipmentDisplayStatus
from core.labs.models.activity.computing_activity import ComputingActivityStatus

from .equipment import with_display_status


def get_equipment_status_summary() -> dict[str, Any]:
    """Non-deleted equipment counted once each by computed ``display_status``. One query."""
    inventory = with_display_status(Equipment.objects.filter(deleted_at__isnull=True))
    return status_summary(inventory, field="display_status", choices=EquipmentDisplayStatus.choices)


def get_computing_activity_summary() -> dict[str, Any]:
    """Missing telemetry is unknown, not inferred offline; no user information."""
    return status_summary(
        Equipment.objects.filter(deleted_at__isnull=True, computing_profile__isnull=False),
        field="activity__status",
        choices=ComputingActivityStatus.choices,
    )


def get_equipment_category_status_summary(*, category_id: int) -> dict[str, Any]:
    """Count one equipment category by computed ``display_status``. One query."""
    inventory = with_display_status(Equipment.objects.filter(deleted_at__isnull=True, kind__category_id=category_id))
    return status_summary(inventory, field="display_status", choices=EquipmentDisplayStatus.choices)
