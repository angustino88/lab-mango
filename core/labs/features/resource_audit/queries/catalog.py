"""Audit catalog: the compact, cursor-paged list of auditable resources the audit tool keeps offline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.core import signing
from django.db.models import DateTimeField, Exists, F, Model, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.labs.features.resource_audit.exceptions import InvalidCatalogCursorError
from core.labs.models.resource.base.downtime import condition_expression, outer_windows
from core.labs.models.resource.bench.bench import Bench
from core.labs.models.resource.equipment.equipment import Equipment
from core.labs.models.resource.license.license import License, LicenseStatusRecord
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.station import Station

CATALOG_PAGE_SIZE_DEFAULT = 500
CATALOG_PAGE_SIZE_MAX = 1000
_CURSOR_SALT = "labs.resource_audit.catalog"

# Fixed order: the cursor stores the index of the type it stopped in.
CATALOG_RESOURCE_TYPES: tuple[str, ...] = ("equipment", "bench", "station", "room", "license")


@dataclass(frozen=True, slots=True)
class AuditCatalogPage:
    items: list[dict[str, Any]]
    page_size: int
    next_cursor: str | None
    server_time: datetime


def _base_values(queryset: QuerySet) -> QuerySet:
    # Explicit columns only: License.identifier (the license key) is never selected.
    return queryset.values("id", "uid", "sku", "name", "modified", "deleted_at")


# License status is the newest status-history record (index ``license_status_latest_idx``).
# Room, station and bench status is the stored ``lifecycle_status``; condition (all but licenses) is
# computed from the downtime window covering now (resource-status-and-downtime.md).
_STATUS_RECORDS: dict[str, tuple[type[Model], str]] = {
    "license": (LicenseStatusRecord, "license"),
}


def _latest_status(resource_type: str) -> Coalesce:
    model, owner = _STATUS_RECORDS[resource_type]
    records = model._default_manager.filter(**{owner: OuterRef("pk")})
    newest = records.order_by("-created", "-id").values("status")[:1]
    return Coalesce(Subquery(newest), Value(""))


def _typed_querysets() -> dict[str, QuerySet]:
    blank = Value("")
    no_expiry = Value(None, output_field=DateTimeField())
    return {
        "equipment": _base_values(Equipment.all_objects.all()).annotate(
            serial=F("serial_number"),
            state=F("lifecycle_state"),
            item_condition=condition_expression(Equipment),
            location_name=blank,
            expires=no_expiry,
        ),
        "bench": _base_values(Bench.all_objects.all()).annotate(
            serial=blank,
            state=F("lifecycle_status"),
            item_condition=condition_expression(Bench),
            location_name=Coalesce(F("setup_location__name"), blank),
            expires=no_expiry,
        ),
        "station": _base_values(Station.all_objects.all()).annotate(
            serial=blank,
            state=F("lifecycle_status"),
            item_condition=condition_expression(Station),
            location_name=Coalesce(F("room__name"), blank),
            expires=no_expiry,
        ),
        "room": _base_values(Room.all_objects.all()).annotate(
            serial=blank,
            state=F("lifecycle_status"),
            item_condition=condition_expression(Room),
            location_name=Coalesce(F("building__name"), blank),
            expires=no_expiry,
        ),
        "license": _base_values(License.all_objects.all()).annotate(
            serial=blank,
            state=_latest_status("license"),
            item_condition=blank,
            location_name=blank,
            expires=F("expiry_date"),
        ),
    }


def _changed_since(resource_type: str, since: datetime) -> Q:
    """The row itself changed or was deleted, its location parent was renamed, or it got a new status record.

    Parent renames and license status records do not touch the row's own ``modified``, so without these
    terms a delta sync would keep a stale location name or status. Lifecycle is a column, so a change
    is caught by ``modified``. Condition is computed from downtime windows, so a window written, started
    or ended since ``since`` also counts.
    """
    condition = Q(modified__gte=since) | Q(deleted_at__gte=since)
    if resource_type == "bench":
        condition |= Q(setup_location__modified__gte=since)
    elif resource_type == "station":
        condition |= Q(room__modified__gte=since)
    elif resource_type == "room":
        condition |= Q(building__modified__gte=since)
    if resource_type in _STATUS_RECORDS:
        model, owner = _STATUS_RECORDS[resource_type]
        condition |= Q(Exists(model._default_manager.filter(**{owner: OuterRef("pk"), "created__gte": since})))
    if resource_type in _DOWNTIME_MODELS:
        now = timezone.now()
        windows = outer_windows(_DOWNTIME_MODELS[resource_type]).filter(
            Q(modified__gte=since)
            | Q(starts_at__gte=since, starts_at__lte=now)
            | Q(ends_at__gte=since, ends_at__lte=now)
        )
        condition |= Q(Exists(windows))
    return condition


_DOWNTIME_MODELS: dict[str, type[Model]] = {"equipment": Equipment, "bench": Bench, "station": Station, "room": Room}


def _project(resource_type: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": row["uid"],
        "resource_type": resource_type,
        "sku": row["sku"],
        "name": row["name"],
        "serial_number": row["serial"] or "",
        "status": row["state"] or "",
        "condition": row["item_condition"] or "",
        "location": row["location_name"] or "",
        "expiry_date": row["expires"],
        "updated_at": max(filter(None, (row["modified"], row["deleted_at"]))),
        "deleted": row["deleted_at"] is not None,
    }


def _encode(
    *, type_index: int, after_id: int, changed_since: datetime | None, server_time: datetime, page_size: int
) -> str:
    return signing.dumps(
        {
            "t": type_index,
            "a": after_id,
            "c": changed_since.isoformat() if changed_since else None,
            "s": server_time.isoformat(),
            "p": page_size,
        },
        salt=_CURSOR_SALT,
    )


def _decode(cursor: str) -> tuple[int, int, datetime | None, datetime, int]:
    try:
        payload = signing.loads(cursor, salt=_CURSOR_SALT)
        type_index, after_id, page_size = int(payload["t"]), int(payload["a"]), int(payload["p"])
        changed_since = parse_datetime(payload["c"]) if payload["c"] else None
        server_time = parse_datetime(payload["s"])
    except (signing.BadSignature, KeyError, TypeError, ValueError) as error:
        raise InvalidCatalogCursorError("The cursor is invalid or was not issued by this server.") from error
    if server_time is None or not 0 <= type_index < len(CATALOG_RESOURCE_TYPES) or after_id < 0:
        raise InvalidCatalogCursorError("The cursor is invalid or was not issued by this server.")
    if not 1 <= page_size <= CATALOG_PAGE_SIZE_MAX:
        raise InvalidCatalogCursorError("The cursor is invalid or was not issued by this server.")
    return type_index, after_id, changed_since, server_time, page_size


def list_audit_catalog(
    *,
    changed_since: datetime | None = None,
    cursor: str | None = None,
    page_size: int = CATALOG_PAGE_SIZE_DEFAULT,
) -> AuditCatalogPage:
    """Return one page of auditable resources of every type, ordered by (type, id).

    Without ``changed_since`` it is a full download of live rows. With it, rows created, changed or
    soft-deleted at or after that time are returned, deleted rows flagged ``deleted``; so are rows whose
    location parent was renamed or that got a new status record (``_changed_since``). Pages after the
    first come from ``cursor`` only, which carries the filter, the page size and the ``server_time`` of
    the first page; the client stores that ``server_time`` as its next ``changed_since``, so changes made
    while it was paging are picked up by the next sync. At most one query per resource type per page.
    """
    if cursor is not None:
        type_index, after_id, changed_since, server_time, page_size = _decode(cursor)
    else:
        if not 1 <= page_size <= CATALOG_PAGE_SIZE_MAX:
            raise ValueError("page_size out of range")
        type_index, after_id, server_time = 0, 0, timezone.now()

    querysets = _typed_querysets()
    items: list[dict[str, Any]] = []
    next_cursor: str | None = None
    for index in range(type_index, len(CATALOG_RESOURCE_TYPES)):
        resource_type = CATALOG_RESOURCE_TYPES[index]
        queryset = querysets[resource_type]
        if changed_since is None:
            queryset = queryset.filter(deleted_at__isnull=True)
        else:
            queryset = queryset.filter(_changed_since(resource_type, changed_since))
        if index == type_index and after_id:
            queryset = queryset.filter(id__gt=after_id)
        remaining = page_size - len(items)
        rows = list(queryset.order_by("id")[: remaining + 1])
        items.extend(_project(resource_type, row) for row in rows[:remaining])
        if len(rows) > remaining:
            next_cursor = _encode(
                type_index=index,
                after_id=rows[remaining - 1]["id"],
                changed_since=changed_since,
                server_time=server_time,
                page_size=page_size,
            )
            break
        if len(items) == page_size and index + 1 < len(CATALOG_RESOURCE_TYPES):
            # The page is full exactly at a type boundary; continue with the next type.
            next_cursor = _encode(
                type_index=index + 1,
                after_id=0,
                changed_since=changed_since,
                server_time=server_time,
                page_size=page_size,
            )
            break
    return AuditCatalogPage(items=items, page_size=page_size, next_cursor=next_cursor, server_time=server_time)


__all__ = [
    "CATALOG_PAGE_SIZE_DEFAULT",
    "CATALOG_PAGE_SIZE_MAX",
    "CATALOG_RESOURCE_TYPES",
    "AuditCatalogPage",
    "list_audit_catalog",
]
