"""Read-only placement queries (redesign step 1)."""

from datetime import datetime

from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce

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


def highest_rack_unit(*, station_id: int) -> int | None:
    """Top rack unit used by active rack-mounted equipment at the station, or None. 1 query."""
    rows = EquipmentAssignment.all_placements.filter(
        station_id=station_id,
        unassigned_at__isnull=True,
        rack_unit__isnull=False,
        equipment__deleted_at__isnull=True,
    ).values_list("rack_unit", "rack_unit_height")
    return max((unit + height - 1 for unit, height in rows), default=None)


def rack_mounted_rows(*, station_ids):
    """Active rack-mounted equipment of the stations, bottom unit first. 1 query."""
    return (
        EquipmentAssignment.all_placements.filter(
            station_id__in=list(station_ids),
            unassigned_at__isnull=True,
            rack_unit__isnull=False,
            equipment__deleted_at__isnull=True,
        )
        .order_by("station_id", "rack_unit", "pk")
        .values(
            "station_id",
            "equipment_id",
            "equipment__sku",
            "equipment__name",
            "equipment__kind__category__name",
            "equipment__power_draw_w",
            "rack_unit",
            "rack_unit_height",
            "rack_face",
        )
    )


def station_installed_totals(*, station_ids) -> dict[int, dict[str, float]]:
    """Power draw (W) and weight (kg) of active equipment at each station: on its benches and placed directly.

    Units without a recorded power draw or weight count as 0. Two queries, whatever the number of stations.
    """
    ids = list(station_ids)
    totals: dict[int, dict[str, float]] = {
        station_id: {"power_w": 0.0, "weight_kg": 0.0, "units": 0} for station_id in ids
    }
    active = EquipmentAssignment.all_placements.filter(unassigned_at__isnull=True, equipment__deleted_at__isnull=True)
    for station_key, rows in (
        ("station_id", active.filter(station_id__in=ids)),
        ("bench__setup_location_id", active.filter(bench__setup_location_id__in=ids, bench__deleted_at__isnull=True)),
    ):
        for row in rows.values(at_station=F(station_key)).annotate(
            power=Coalesce(Sum("equipment__power_draw_w"), 0),
            weight=Coalesce(Sum("equipment__weight_kg"), 0, output_field=DecimalField()),
            units=Count("pk"),
        ):
            entry = totals.setdefault(row["at_station"], {"power_w": 0.0, "weight_kg": 0.0, "units": 0})
            entry["power_w"] += float(row["power"])
            entry["weight_kg"] += float(row["weight"])
            entry["units"] += row["units"]
    return totals
