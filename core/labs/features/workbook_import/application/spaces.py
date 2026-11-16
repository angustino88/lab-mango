"""Rooms, stations, station slots and benches, created through the owning features' public commands."""

from __future__ import annotations

from typing import Any

from core.labs.features.benches.public import change_bench_lifecycle, create_bench
from core.labs.features.downtime.public import ScheduleDowntimeInput, schedule_downtime
from core.labs.features.locations.public import (
    change_room_lifecycle,
    change_station_lifecycle,
    create_room,
    create_station,
    create_station_slot,
    generate_room_slots,
)
from core.labs.models import (
    BenchGroup,
    BenchType,
    Building,
    City,
    Room,
    RoomSlot,
    Station,
    StationSlot,
    StationType,
)
from core.labs.models.resource.base.downtime import DowntimeReason
from core.labs.models.resource.base.resource import Department, Group

from .context import ImportRun, Row
from .references import Catalog

IMPORT_NOTE = "Imported from the data workbook."

# Old seven-value room/station status (template v1) → (lifecycle, access, condition, note).
_LEGACY_SPACE_STATUS: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "available": ("in_service", "open", None, None),
    "reserved": ("in_service", None, None, "Reserved is computed from bookings; imported as in service."),
    "issue": ("in_service", None, "out_of_service", None),
    "closed": ("in_service", None, "out_of_service", None),
    "maintenance": ("in_service", None, "in_maintenance", None),
    "restricted": ("in_service", "restricted", None, None),
    "retired": ("retired", None, None, None),
}
# Old bench status (template v1) → (lifecycle, condition, note).
_LEGACY_BENCH_STATUS: dict[str, tuple[str, str | None, str | None]] = {
    "planned": ("planned", None, None),
    "available": ("in_service", None, None),
    "reserved": ("in_service", None, "Reserved is computed from bookings; imported as in service."),
    "active": ("in_service", None, "Active is computed from bookings and sessions; imported as in service."),
    "maintenance": ("in_service", "in_maintenance", None),
    "out of service": ("in_service", "out_of_service", None),
    "retired": ("retired", None, None),
}


def _status_key(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def _present(row: Row, keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if row.get(key) is not None}


def _owned(run: ImportRun, catalog: Catalog, row: Row, *, with_department: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if with_department:
        department = catalog.optional(row, "department", Department)
        if department is not None:
            data["department_id"] = department
    group = catalog.optional(row, "group", Group)
    if group is not None:
        data["group_id"] = group
    owner = catalog.user(row)
    if owner is not None:
        data["owner_id"] = owner
    return data


def space_state(run: ImportRun, row: Row, *, legacy: dict[str, tuple]) -> tuple[str, str | None, str | None]:
    """Lifecycle, access and condition from the v2 columns, or from a v1 ``Status`` value."""
    lifecycle = row.get("lifecycle_status")
    access = row.get("access_policy")
    condition = row.get("condition")
    status = row.get("legacy_status")
    if status is not None and lifecycle is None and access is None and condition is None:
        mapped = legacy.get(_status_key(status))
        if mapped is None:
            raise run.fail(
                row,
                f"Unknown status '{status}'. Use the Lifecycle, Access and Condition columns.",
                key="legacy_status",
                code="invalid_value",
            )
        if len(mapped) == 4:
            lifecycle, access, condition, note = mapped
        else:
            lifecycle, condition, note = mapped
        if note:
            run.row_warning(row, note, key="legacy_status", code="status_mapped")
    lifecycle = lifecycle or "in_service"
    if lifecycle == "retired" and condition not in (None, "operational"):
        raise run.fail(row, "A retired resource has no condition; leave Condition empty.", key="condition")
    return lifecycle, access, None if condition == "operational" else condition


def open_downtime(run: ImportRun, resource_type: str, resource_id: int, condition: str | None) -> None:
    if condition is None:
        return
    reason = DowntimeReason.MAINTENANCE if condition == "in_maintenance" else DowntimeReason.FAULT
    schedule_downtime(
        ScheduleDowntimeInput(
            resource_type=resource_type, resource_id=resource_id, condition=condition, reason=reason, notes=IMPORT_NOTE
        ),
        actor=run.actor,
    )


def _by_sku(run: ImportRun, catalog: Catalog, row: Row, key: str, model: type) -> int | None:
    value = row.get(key)
    return None if value is None else catalog.one(row, key, model, "sku", value)


def import_spaces(run: ImportRun) -> None:
    catalog = Catalog(run)

    def room(row: Row) -> str:
        lifecycle, access, condition = space_state(run, row, legacy=_LEGACY_SPACE_STATUS)
        data = _present(
            row,
            (
                "sku",
                "name",
                "label",
                "remark",
                "map_url",
                "length_m",
                "width_m",
                "floor",
                "layout_rows",
                "layout_columns",
                "usable_height_m",
                "floor_plan_revision",
                "floor_plan_url",
                "max_occupancy",
                "power_capacity_w",
                "cooling_capacity_w",
                "network_port_capacity",
                "utilities",
            ),
        )
        data.update(_owned(run, catalog, row))
        country = catalog.country(row)
        if country is not None:
            data["country_id"] = country
        city = catalog.optional(row, "city", City, "name", **({"country_id": country} if country else {}))
        if city is not None:
            data["city_id"] = city
        building = catalog.optional(row, "building", Building, "name", **({"city_id": city} if city else {}))
        if building is not None:
            data["building_id"] = building
        created = create_room(actor=run.actor, **data)
        if created.layout_rows and created.layout_columns:
            generate_room_slots(room_id=created.pk, actor=run.actor)
        if access == "restricted":
            change_room_lifecycle(
                room_id=created.pk, actor=run.actor, access_policy="restricted", metadata={"source": "workbook_import"}
            )
        open_downtime(run, "room", created.pk, condition)
        if lifecycle == "retired":
            change_room_lifecycle(
                room_id=created.pk, actor=run.actor, lifecycle_status="retired", metadata={"source": "workbook_import"}
            )
        return "created"

    run.each("rooms", room)

    def station(row: Row) -> str:
        lifecycle, access, condition = space_state(run, row, legacy=_LEGACY_SPACE_STATUS)
        data = _present(
            row,
            (
                "sku",
                "name",
                "label",
                "remark",
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
                "utilities",
                "safety_classification",
            ),
        )
        data.update(_owned(run, catalog, row))
        station_type = catalog.optional(row, "type", StationType)
        if station_type is not None:
            data["type_id"] = station_type
        room_id = _by_sku(run, catalog, row, "room", Room)
        if room_id is not None:
            data["room_id"] = room_id
        if row.get("slot") is not None:
            if room_id is None:
                raise run.fail(row, "A room slot needs the Room Asset Tag.", key="slot")
            data["slot_id"] = catalog.one(row, "slot", RoomSlot, "slot_code", row.get("slot"), room_id=room_id)
        coordinates = [row.get(key) for key in ("position_x", "position_y", "position_z")]
        if any(value is not None for value in coordinates):
            data["position"] = [float(value or 0) for value in coordinates]
        created = create_station(actor=run.actor, **data)
        if access == "restricted":
            change_station_lifecycle(
                station_id=created.pk,
                actor=run.actor,
                access_policy="restricted",
                metadata={"source": "workbook_import"},
            )
        open_downtime(run, "station", created.pk, condition)
        if lifecycle == "retired":
            change_station_lifecycle(
                station_id=created.pk,
                actor=run.actor,
                lifecycle_status="retired",
                metadata={"source": "workbook_import"},
            )
        return "created"

    run.each("stations", station)

    def station_slot(row: Row) -> str:
        station_id = catalog.one(row, "station", Station, "sku", row.get("station"))
        data = _present(
            row,
            (
                "position_index",
                "slot_code",
                "label",
                "status",
                "width_mm",
                "depth_mm",
                "height_mm",
                "max_load_kg",
                "power_capacity_w",
                "network_port_count",
                "utilities",
            ),
        )
        types = catalog.many(row, "compatible_bench_types", BenchType)
        create_station_slot(station_id=station_id, actor=run.actor, compatible_bench_types=types, **data)
        return "created"

    run.each("station_slots", station_slot, natural_key="__row__")

    def bench(row: Row) -> str:
        lifecycle, _, condition = space_state(run, row, legacy=_LEGACY_BENCH_STATUS)
        data = _present(
            row,
            (
                "sku",
                "name",
                "remark",
                "description",
                "documentation_url",
                "criticality",
                "requested_power_w",
                "requested_load_kg",
                "requested_cooling_w",
                "required_utilities",
                "commissioning_date",
                "last_inspected_at",
                "next_inspection_due_at",
            ),
        )
        data.update(_owned(run, catalog, row, with_department=False))
        department = row.get("department")
        if department is not None:
            group_id = data.get("group_id")
            group_department = (
                None
                if group_id is None
                else Group.objects.filter(pk=group_id).values_list("department__name", flat=True).first()
            )
            if group_department is None or group_department.casefold() != department.casefold():
                raise run.fail(
                    row,
                    "A bench takes its department from its group; pick a group of that department.",
                    key="department",
                )
        bench_group = catalog.optional(row, "bench_group", BenchGroup)
        if bench_group is not None:
            data["bench_group_id"] = bench_group
        bench_type = catalog.optional(row, "type", BenchType)
        if bench_type is not None:
            data["type_id"] = bench_type
        station_id = _by_sku(run, catalog, row, "station", Station)
        if station_id is not None:
            data["setup_location_id"] = station_id
        if row.get("station_slot") is not None:
            if station_id is None:
                raise run.fail(row, "A station slot needs the Station Asset Tag.", key="station_slot")
            data["station_slot_id"] = catalog.one(
                row, "station_slot", StationSlot, "slot_code", row.get("station_slot"), station_id=station_id
            )
        # Created in service (or planned); retirement is a lifecycle change after the downtime check.
        data["lifecycle_status"] = "planned" if lifecycle == "planned" else "in_service"
        created = create_bench(actor=run.actor, **data)
        open_downtime(run, "bench", created.pk, condition)
        if lifecycle == "retired":
            change_bench_lifecycle(bench_id=created.pk, actor=run.actor, lifecycle_status="retired")
        return "created"

    run.each("benches", bench)


__all__ = ["IMPORT_NOTE", "import_spaces", "open_downtime", "space_state"]
