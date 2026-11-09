"""Compose graphic-only placement context through resource-owned public read facades."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from django.core import signing
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from core.labs.features.benches.public import bench_mapping_rows, get_bench_for_mapping
from core.labs.features.equipment.public import (
    equipment_mapping_rows,
    get_equipment_for_mapping,
)
from core.labs.features.licenses.public import active_license_assignment_mapping_rows, license_mapping_rows
from core.labs.features.locations.public import (
    get_room_for_mapping,
    get_station_for_mapping,
    room_mapping_rows,
    room_slot_mapping_rows,
    station_mapping_rows,
    station_slot_mapping_rows,
)

COLLECTIONS = (
    "rooms",
    "room_slots",
    "stations",
    "station_slots",
    "benches",
    "equipment",
    "licenses",
    "license_assignments",
)
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
_CURSOR_SALT = "labs.resource-mappings.cursor"


class MappingQueryError(ValueError):
    """A mapping cursor is malformed, expired, or bound to another collection/context."""


def _root_resource(resource_type: str, resource_id: int) -> Any | None:
    selectors: dict[str, Callable[..., Any]] = {
        "rooms": get_room_for_mapping,
        "stations": get_station_for_mapping,
        "benches": get_bench_for_mapping,
        "equipment": get_equipment_for_mapping,
    }
    argument = {
        "rooms": "room_id",
        "stations": "station_id",
        "benches": "bench_id",
        "equipment": "equipment_id",
    }[resource_type]
    return selectors[resource_type](**{argument: resource_id})


def _materialize(
    queryset: QuerySet,
    collection: str,
    *,
    root_type: str,
    root_id: int,
    page_size: int,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = queryset.count()
    direction = "next"
    anchor = None
    if cursor:
        try:
            payload = signing.loads(cursor, salt=_CURSOR_SALT, max_age=86400)
        except signing.BadSignature as exc:
            raise MappingQueryError("Invalid or expired cursor.") from exc
        if (
            payload.get("root_type") != root_type
            or payload.get("root_id") != root_id
            or payload.get("collection") != collection
            or payload.get("page_size") != page_size
            or payload.get("direction") not in {"next", "previous"}
            or type(payload.get("anchor")) is not int
        ):
            raise MappingQueryError("Cursor does not match this mapping request.")
        anchor = payload.get("anchor")
        direction = payload["direction"]
        if type(anchor) is not int or anchor < 1:
            raise MappingQueryError("Invalid cursor position.")

    pin_root = collection == root_type
    if pin_root:
        queryset = queryset.annotate(
            _mapping_root_order=Case(
                When(pk=root_id, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )

    if anchor is not None:
        if pin_root:
            anchor_row = queryset.filter(pk=anchor).values("_mapping_root_order").first()
            if anchor_row is None:
                raise MappingQueryError("Cursor position is no longer present.")
            anchor_root_order = anchor_row["_mapping_root_order"]
            if direction == "next":
                queryset = queryset.filter(
                    Q(_mapping_root_order__gt=anchor_root_order)
                    | Q(_mapping_root_order=anchor_root_order, pk__gt=anchor)
                )
            else:
                queryset = queryset.filter(
                    Q(_mapping_root_order__lt=anchor_root_order)
                    | Q(_mapping_root_order=anchor_root_order, pk__lt=anchor)
                )
        elif direction == "next":
            queryset = queryset.filter(pk__gt=anchor)
        else:
            queryset = queryset.filter(pk__lt=anchor)

    ordering = ("_mapping_root_order", "pk") if pin_root else ("pk",)
    if direction == "previous":
        ordering = cast(tuple[str, ...], tuple(f"-{field}" for field in ordering))
    rows = list(queryset.order_by(*ordering)[: page_size + 1])
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    if direction == "previous":
        rows.reverse()

    def token(*, row: dict[str, Any], token_direction: str) -> str:
        return signing.dumps(
            {
                "root_type": root_type,
                "root_id": root_id,
                "collection": collection,
                "page_size": page_size,
                "anchor": row["id"],
                "direction": token_direction,
            },
            salt=_CURSOR_SALT,
        )

    has_previous = anchor is not None and (direction == "next" or has_more)
    has_next = has_more if direction == "next" else anchor is not None
    pagination = {
        "count": total,
        "page_size": page_size,
        "next_cursor": token(row=rows[-1], token_direction="next") if rows and has_next else None,
        "previous_cursor": token(row=rows[0], token_direction="previous") if rows and has_previous else None,
    }
    return rows, pagination


def _scope_querysets(*, root_type: str, root: dict[str, Any]) -> tuple[dict[str, QuerySet], dict[str, Any]]:
    room_ids: list[int] = []
    station_ids: list[int] = []
    bench_ids: list[int] = []
    equipment_ids: list[int] = []

    if root_type == "rooms":
        room_ids = [root["id"]]
    elif root_type == "stations":
        station_ids = [root["id"]]
        if root["room_id"] and get_room_for_mapping(room_id=root["room_id"]):
            room_ids = [root["room_id"]]
    elif root_type == "benches":
        bench_ids = [root["id"]]
        if root["setup_location_id"]:
            station = get_station_for_mapping(station_id=root["setup_location_id"])
            if station:
                station_ids = [station["id"]]
                if station["room_id"] and get_room_for_mapping(room_id=station["room_id"]):
                    room_ids = [station["room_id"]]
    else:
        equipment_ids = [root["id"]]
        equipment_rows = list(equipment_mapping_rows(equipment_ids=equipment_ids)[:1])
        if equipment_rows and equipment_rows[0]["mapping_bench_id"]:
            equipment_ids = []
            bench = get_bench_for_mapping(bench_id=equipment_rows[0]["mapping_bench_id"])
            if bench:
                bench_ids = [bench["id"]]
                if bench["setup_location_id"]:
                    station = get_station_for_mapping(station_id=bench["setup_location_id"])
                    if station:
                        station_ids = [station["id"]]
                        if station["room_id"] and get_room_for_mapping(room_id=station["room_id"]):
                            room_ids = [station["room_id"]]

    room_query = room_mapping_rows(room_ids=room_ids)
    room_slot_query = room_slot_mapping_rows(room_ids=room_ids)
    station_query = station_mapping_rows(station_ids=station_ids, room_ids=room_ids)
    station_slot_query = station_slot_mapping_rows(station_ids=station_ids, room_ids=room_ids)
    bench_query = bench_mapping_rows(bench_ids=bench_ids, station_ids=station_ids, room_ids=room_ids)
    equipment_query = equipment_mapping_rows(
        equipment_ids=equipment_ids,
        bench_ids=bench_ids,
        station_ids=station_ids,
        room_ids=room_ids,
    )
    license_assignment_query = active_license_assignment_mapping_rows(
        equipment_ids=equipment_ids,
        bench_ids=bench_ids,
        station_ids=station_ids,
        room_ids=room_ids,
    )
    license_ids = license_assignment_query.order_by().values("license_id")
    license_query = license_mapping_rows(license_ids=license_ids)

    sources = {
        "rooms": room_query,
        "room_slots": room_slot_query,
        "stations": station_query,
        "station_slots": station_slot_query,
        "benches": bench_query,
        "equipment": equipment_query,
        "licenses": license_query,
        "license_assignments": license_assignment_query,
    }
    ids = {"room_ids": room_ids, "station_ids": station_ids, "bench_ids": bench_ids, "equipment_ids": equipment_ids}
    return sources, ids


def get_resource_mapping(
    *,
    resource_type: str,
    resource_id: int,
    page_size: int = DEFAULT_PAGE_SIZE,
    cursors: dict[str, str | None] | None = None,
) -> dict[str, Any] | None:
    """Return one flat, independently cursor-paginated graphic placement projection."""
    root = _root_resource(resource_type, resource_id)
    if root is None:
        return None
    sources, ids = _scope_querysets(root_type=resource_type, root=root)
    data: dict[str, list[dict[str, Any]]] = {}
    pagination: dict[str, dict[str, Any]] = {}
    for collection in COLLECTIONS:
        rows, page_meta = _materialize(
            sources[collection],
            collection,
            root_type=resource_type,
            root_id=resource_id,
            page_size=page_size,
            cursor=(cursors or {}).get(collection),
        )
        data[collection] = [_shape_row(collection, row) for row in rows]
        pagination[collection] = page_meta

    return {"data": data, "meta": {"pagination": pagination}}


def _shape_row(collection: str, row: Any) -> dict[str, Any]:
    if collection == "rooms":
        return {key: row[key] for key in ("id", "uid", "sku", "name", "layout_rows", "layout_columns")}
    if collection == "room_slots":
        return {
            key: row[key]
            for key in (
                "id",
                "room_id",
                "row_index",
                "col_index",
                "slot_code",
                "x_mm",
                "y_mm",
                "width_mm",
                "depth_mm",
                "orientation_degrees",
            )
        }
    if collection == "stations":
        return {key: row[key] for key in ("id", "uid", "sku", "name", "room_id", "slot_id")}
    if collection == "station_slots":
        return {key: row[key] for key in ("id", "station_id", "position_index", "slot_code", "label")}
    if collection == "benches":
        return {key: row[key] for key in ("id", "uid", "sku", "name", "setup_location_id", "station_slot_id")}
    if collection == "equipment":
        return {
            "id": row["id"],
            "uid": row["uid"],
            "sku": row["sku"],
            "name": row["name"],
            "category": {"id": row["kind__category_id"], "name": row["kind__category__name"]},
            "bench_id": row["mapping_bench_id"],
            "bench_assignment": (
                {
                    "id": row["mapping_assignment_id"],
                    "role": row["mapping_role"],
                    "position": row["mapping_position"],
                    "monitor": row["mapping_monitor"],
                    "assigned_at": row["mapping_assigned_at"],
                }
                if row["mapping_assignment_id"] is not None
                else None
            ),
        }
    if collection == "licenses":
        return {
            "id": row["id"],
            "uid": row["uid"],
            "sku": row["sku"],
            "name": row["name"],
            "category": {"id": row["category_id"], "name": row["category__name"]},
        }
    return {key: row[key] for key in ("id", "equipment_id", "license_id", "assigned_at")}
