"""Bench placement helpers and the interface catalog for monitoring.

Devices are matched by registered hardware IDs (``queries/hardware_ids.py``), never by
``Equipment.serial_number``.
"""

from typing import Any

from django.db.models import OuterRef, QuerySet

from core.labs.models import EquipmentAssignment, EquipmentInterface


def monitoring_interfaces() -> tuple[str, ...]:
    """Bounded catalog hint; does not claim the agent has a collector for each name."""
    return tuple(EquipmentInterface.objects.order_by("name", "pk").values_list("name", flat=True)[:200])


def active_bench_assignments(*, equipment_field: str) -> QuerySet[EquipmentAssignment]:
    """Active bench placement of the unit named by ``OuterRef(equipment_field)``, for subqueries."""
    return EquipmentAssignment.objects.filter(
        equipment_id=OuterRef(equipment_field),
        unassigned_at__isnull=True,
        bench__isnull=False,
        bench__deleted_at__isnull=True,
    ).order_by("pk")


def equipment_ids_on_bench(*, bench_id: int) -> QuerySet[EquipmentAssignment, dict[str, Any]]:
    """Ids of the active units placed on one bench, for ``__in`` filters."""
    return EquipmentAssignment.objects.filter(
        bench_id=bench_id, unassigned_at__isnull=True, equipment__deleted_at__isnull=True
    ).values("equipment_id")
