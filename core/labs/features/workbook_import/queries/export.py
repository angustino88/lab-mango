"""Rows for the data export: the current rooms, stations, slots, benches, equipment and placements.

The export is the template with these sheets filled in, in the same columns, so an exported file can be edited
and imported again in update mode (``upsert``). Every value is written in the form the importer reads back:
choice labels, Yes/No, names of references, asset tags of related records, and ``name=value`` utilities.

Query budget: one query per sheet (plus one prefetch for the slot bench types); the condition is a correlated
subquery annotation, never a query per row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from core.labs.models import Bench, Equipment, Room, Station, StationSlot
from core.labs.models.resource.base.downtime import condition_expression
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

from .sheets import CHOICE_LISTS, CHOICE_VALUES, MAX_DATA_ROWS, SHEETS_BY_KEY, template_columns

EXPORTED_SHEETS = ("rooms", "stations", "station_slots", "benches", "equipment", "bench_placements")


def choice_label(list_key: str, value: str | None) -> str | None:
    """Stored value → the dropdown label the importer accepts; ``None`` when this list cannot import it."""
    if value is None:
        return None
    for label in CHOICE_LISTS[list_key]:
        if CHOICE_VALUES[list_key].get(label.lower()) == value:
            return label
    return None


def utilities_text(value: Any) -> str | None:
    """``{"230V": True, "ethernet": 2}`` → ``"230V, ethernet=2"`` (the importer's format)."""
    if not value or not isinstance(value, dict):
        return None
    return ", ".join(str(name) if amount is True else f"{name}={amount}" for name, amount in value.items())


def _cell(value: Any) -> Any:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        # Excel has no time zones: write the local wall-clock time, as the importer reads it.
        return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value
    return value


def _name(related: Any, attribute: str = "name") -> Any:
    return None if related is None else getattr(related, attribute)


def _ordered(sheet_key: str, values: dict[str, Any]) -> tuple[Any, ...]:
    """Values by column key → one row in template column order. A list fills numbered columns in turn."""
    lists = {key: list(value) for key, value in values.items() if isinstance(value, list)}
    row = []
    for column in template_columns(SHEETS_BY_KEY[sheet_key]):
        if column.key in lists:
            row.append(_cell(lists[column.key].pop(0)) if lists[column.key] else None)
        else:
            row.append(_cell(values.get(column.key)))
    return tuple(row)


def _owned(resource: Any) -> dict[str, Any]:
    return {
        "department": _name(resource.department),
        "group": _name(resource.group),
        "owner": _name(resource.owner, "username"),
    }


def _active(queryset: QuerySet) -> QuerySet:
    return queryset.filter(deleted_at__isnull=True).annotate(_condition=condition_expression(queryset.model))


def _rooms() -> list[dict[str, Any]]:
    rows = []
    queryset = _active(Room.objects.select_related("department", "group", "owner", "country", "city", "building"))
    for room in queryset.order_by("sku")[: MAX_DATA_ROWS + 1]:
        rows.append(
            {
                **{
                    key: getattr(room, key)
                    for key in (
                        "sku",
                        "name",
                        "label",
                        "floor",
                        "length_m",
                        "width_m",
                        "usable_height_m",
                        "layout_rows",
                        "layout_columns",
                        "floor_plan_revision",
                        "floor_plan_url",
                        "map_url",
                        "max_occupancy",
                        "power_capacity_w",
                        "cooling_capacity_w",
                        "network_port_capacity",
                        "remark",
                    )
                },
                **_owned(room),
                "country": _name(room.country),
                "city": _name(room.city),
                "building": _name(room.building),
                "utilities": utilities_text(room.utilities),
                "lifecycle_status": choice_label("space_lifecycle", room.lifecycle_status),
                "access_policy": choice_label("access", room.access_policy),
                "condition": choice_label("condition", room._condition),
            }
        )
    return rows


def _stations() -> list[dict[str, Any]]:
    rows = []
    queryset = _active(Station.objects.select_related("department", "group", "owner", "type", "room", "slot"))
    for station in queryset.order_by("sku")[: MAX_DATA_ROWS + 1]:
        position = list(station.position or [])
        rows.append(
            {
                **{
                    key: getattr(station, key)
                    for key in (
                        "sku",
                        "name",
                        "label",
                        "height_mm",
                        "width_mm",
                        "depth_mm",
                        "orientation_degrees",
                        "max_load_kg",
                        "bench_capacity",
                        "max_concurrent_users",
                        "usable_surface_mm2",
                        "power_capacity_w",
                        "power_reserved_w",
                        "cooling_capacity_w",
                        "network_port_capacity",
                        "safety_classification",
                        "remark",
                    )
                },
                **_owned(station),
                "type": _name(station.type),
                "room": _name(station.room, "sku"),
                "slot": _name(station.slot, "slot_code"),
                **{
                    key: position[index] if index < len(position) else None
                    for index, key in enumerate(("position_x", "position_y", "position_z"))
                },
                "utilities": utilities_text(station.utilities),
                "lifecycle_status": choice_label("space_lifecycle", station.lifecycle_status),
                "access_policy": choice_label("access", station.access_policy),
                "condition": choice_label("condition", station._condition),
            }
        )
    return rows


def _station_slots() -> list[dict[str, Any]]:
    queryset = (
        StationSlot.objects.filter(station__deleted_at__isnull=True)
        .select_related("station")
        .prefetch_related("compatible_bench_types")
        .order_by("station__sku", "position_index")
    )
    return [
        {
            **{
                key: getattr(slot, key)
                for key in (
                    "position_index",
                    "slot_code",
                    "label",
                    "width_mm",
                    "depth_mm",
                    "height_mm",
                    "max_load_kg",
                    "power_capacity_w",
                    "network_port_count",
                )
            },
            "station": slot.station.sku,
            "status": choice_label("slot_status", slot.status),
            "utilities": utilities_text(slot.utilities),
            "compatible_bench_types": sorted(item.name for item in slot.compatible_bench_types.all()),
        }
        for slot in queryset[: MAX_DATA_ROWS + 1]
    ]


def _benches() -> list[dict[str, Any]]:
    rows = []
    queryset = _active(
        Bench.objects.select_related("group", "owner", "bench_group", "type", "setup_location", "station_slot")
    )
    for bench in queryset.order_by("sku")[: MAX_DATA_ROWS + 1]:
        rows.append(
            {
                **{
                    key: getattr(bench, key)
                    for key in (
                        "sku",
                        "name",
                        "description",
                        "documentation_url",
                        "criticality",
                        "requested_power_w",
                        "requested_load_kg",
                        "requested_cooling_w",
                        "commissioning_date",
                        "last_inspected_at",
                        "next_inspection_due_at",
                        "remark",
                    )
                },
                "group": _name(bench.group),
                "owner": _name(bench.owner, "username"),
                "bench_group": _name(bench.bench_group),
                "type": _name(bench.type),
                "station": _name(bench.setup_location, "sku"),
                "station_slot": _name(bench.station_slot, "slot_code"),
                "required_utilities": utilities_text(bench.required_utilities),
                "lifecycle_status": choice_label("lifecycle", bench.lifecycle_status),
                "condition": choice_label("condition", bench._condition),
            }
        )
    return rows


def _equipment() -> list[dict[str, Any]]:
    stored_in = dict(
        EquipmentAssignment.objects.filter(
            unassigned_at__isnull=True, room__isnull=False, equipment__deleted_at__isnull=True
        ).values_list("equipment_id", "room__sku")
    )
    rows = []
    queryset = _active(
        Equipment.objects.select_related(
            "kind__category", "type", "manufacturer", "product_model", "department", "group", "owner"
        )
    )
    for unit in queryset.order_by("sku")[: MAX_DATA_ROWS + 1]:
        rows.append(
            {
                **{
                    key: getattr(unit, key)
                    for key in (
                        "sku",
                        "name",
                        "serial_number",
                        "firmware_version",
                        "log_label",
                        "replacement_date",
                        "warranty_until",
                        "power_draw_w",
                        "weight_kg",
                        "calibration_required",
                        "details",
                    )
                },
                **_owned(unit),
                "category": unit.kind.category.name,
                "kind": unit.kind.name,
                "type": _name(unit.type),
                "manufacturer": _name(unit.manufacturer),
                "product_model": _name(unit.product_model),
                # Left blank when the state is not one an import can set (e.g. lost, retired): blank keeps it.
                "lifecycle_state": choice_label("equipment_lifecycle", unit.lifecycle_state),
                "condition": choice_label("condition", unit._condition),
                "storage_room": stored_in.get(unit.pk),
            }
        )
    return rows


def _bench_placements() -> list[dict[str, Any]]:
    queryset = (
        EquipmentAssignment.objects.filter(
            unassigned_at__isnull=True, bench__isnull=False, equipment__deleted_at__isnull=True
        )
        .values("bench__sku", "equipment__sku", "role", "position")
        .order_by("bench__sku", "position", "equipment__sku")
    )
    return [
        {
            "bench": item["bench__sku"],
            "equipment": item["equipment__sku"],
            "role": item["role"],
            "position": item["position"],
        }
        for item in queryset[: MAX_DATA_ROWS + 1]
    ]


_BUILDERS = {
    "rooms": _rooms,
    "stations": _stations,
    "station_slots": _station_slots,
    "benches": _benches,
    "equipment": _equipment,
    "bench_placements": _bench_placements,
}


def export_rows() -> tuple[dict[str, list[tuple[Any, ...]]], list[str]]:
    """Current records per exported sheet key in template column order, and the sheet names that were cut.

    A sheet holds at most ``MAX_DATA_ROWS`` rows (what one import accepts); a longer one is cut and named in
    the second value so the file can say so instead of dropping rows silently.
    """
    rows: dict[str, list[tuple[Any, ...]]] = {}
    truncated: list[str] = []
    for key in EXPORTED_SHEETS:
        values = _BUILDERS[key]()
        if len(values) > MAX_DATA_ROWS:
            truncated.append(SHEETS_BY_KEY[key].name)
        rows[key] = [_ordered(key, item) for item in values[:MAX_DATA_ROWS]]
    return rows, truncated


__all__ = ["EXPORTED_SHEETS", "choice_label", "export_rows", "utilities_text"]
