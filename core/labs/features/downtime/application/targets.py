"""Resolve and lock the resource a downtime window is for, and the benches and equipment it blocks.

Lock order (design note, "Ownership and locks"): room, then its stations, then their benches, each in
primary-key order; a station, then its benches; a bench; an equipment unit. Bench booking writers lock
the bench row and equipment reservation writers the equipment row before they read downtime, so
whichever transaction commits first is seen by the other.
"""

from dataclasses import dataclass
from typing import Any

from django.db import models

from core.labs.models import Bench, Equipment, EquipmentLifecycleState, ResourceLifecycleStatus, Room, Station

RESOURCE_MODELS: dict[str, type[models.Model]] = {
    "room": Room,
    "station": Station,
    "bench": Bench,
    "equipment": Equipment,
}


@dataclass(frozen=True, slots=True)
class Target:
    resource_type: str
    resource: Any  # Room, Station, Bench or Equipment
    bench_ids: tuple[int, ...]
    equipment_ids: tuple[int, ...]

    @property
    def in_service(self) -> bool:
        if self.resource_type == "equipment":
            return self.resource.lifecycle_state == EquipmentLifecycleState.IN_SERVICE
        return self.resource.lifecycle_status == ResourceLifecycleStatus.IN_SERVICE


def _lock_benches(queryset) -> tuple[int, ...]:
    return tuple(queryset.select_for_update().order_by("pk").values_list("pk", flat=True))


def lock_target(resource_type: str, resource_id: int) -> Target:
    """Lock the resource and every bench it covers; raises ``<Model>.DoesNotExist`` when missing."""
    if resource_type == "room":
        room = Room.objects.select_for_update().get(pk=resource_id)
        station_ids = tuple(
            Station.objects.select_for_update().filter(room_id=room.pk).order_by("pk").values_list("pk", flat=True)
        )
        return Target("room", room, _lock_benches(Bench.objects.filter(setup_location_id__in=station_ids)), ())
    if resource_type == "station":
        station = Station.objects.select_for_update().get(pk=resource_id)
        return Target("station", station, _lock_benches(Bench.objects.filter(setup_location_id=station.pk)), ())
    if resource_type == "bench":
        bench = Bench.objects.select_for_update().get(pk=resource_id)
        return Target("bench", bench, (bench.pk,), ())
    equipment = Equipment.objects.select_for_update().get(pk=resource_id, deleted_at__isnull=True)
    return Target("equipment", equipment, (), (equipment.pk,))


__all__ = ["RESOURCE_MODELS", "Target", "lock_target"]
