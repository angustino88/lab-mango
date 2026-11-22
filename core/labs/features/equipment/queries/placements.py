"""Read-only placement queries (redesign step 1)."""

from datetime import datetime

from django.db.models import Q

from core.labs.models.resource.equipment.assignment import EquipmentAssignment


def get_active_placement(*, equipment_id: int) -> EquipmentAssignment:
    """The unit's active placement of any kind. Raises ``EquipmentAssignment.DoesNotExist``. 1 query."""
    return EquipmentAssignment.all_placements.select_related("bench", "station", "room").get(
        equipment_id=equipment_id,
        equipment__deleted_at__isnull=True,
        unassigned_at__isnull=True,
    )


def has_active_placements(*, room_id: int | None = None, station_id: int | None = None) -> bool:
    """Whether any non-deleted unit is placed directly in this room or at this station.

    Callers that delete a room or station hold its row lock; ``place_equipment`` takes the same
    lock before it opens a placement there, so the answer cannot go stale before the delete.
    """
    if (room_id is None) == (station_id is None):
        raise ValueError("Pass exactly one of room_id or station_id.")
    target = {"room_id": room_id} if room_id is not None else {"station_id": station_id}
    return EquipmentAssignment.all_placements.filter(
        unassigned_at__isnull=True, equipment__deleted_at__isnull=True, **target
    ).exists()


def summarize_active_placements(
    *, room_id: int | None = None, station_id: int | None = None, limit: int = 5
) -> tuple[int, list[str], list[str]]:
    """Count non-deleted equipment placed directly in a room or station and return up to ``limit`` labels and category keys."""
    if (room_id is None) == (station_id is None):
        raise ValueError("Pass exactly one of room_id or station_id.")
    target = {"room_id": room_id} if room_id is not None else {"station_id": station_id}
    queryset = EquipmentAssignment.all_placements.filter(
        unassigned_at__isnull=True, equipment__deleted_at__isnull=True, **target
    )
    total = queryset.count()
    if total == 0:
        return 0, [], []
    rows = queryset.order_by("equipment_id").values_list(
        "equipment__sku", "equipment__name", "equipment_id", "equipment__kind__category__key"
    )[:limit]
    labels: list[str] = []
    category_keys: list[str] = []
    for sku, name, equipment_id, category_key in rows:
        sku_text = (sku or "").strip()
        name_text = (name or "").strip()
        if sku_text and name_text:
            labels.append(f"{sku_text} — {name_text}")
        else:
            labels.append(sku_text or name_text or f"#{equipment_id}")
        category_keys.append((category_key or "").strip())
    return total, labels, category_keys


def bench_id_at(*, equipment_id: int, at: datetime) -> int | None:
    """The bench the unit was placed on at ``at``, from placement history, or None. 1 query.

    A placement covers the half-open range [assigned_at, unassigned_at). Deleted benches still count:
    the question is where the unit was, not whether the bench exists today.
    """
    return (
        EquipmentAssignment.objects.filter(equipment_id=equipment_id, assigned_at__lte=at)
        .filter(Q(unassigned_at__isnull=True) | Q(unassigned_at__gt=at))
        .order_by("-assigned_at", "-pk")
        .values_list("bench_id", flat=True)
        .first()
    )


__all__ = ("bench_id_at", "get_active_placement", "has_active_placements", "summarize_active_placements")
