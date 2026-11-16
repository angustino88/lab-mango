"""Rows for the downloadable template: current reference data, so dropdowns list what already exists."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.contrib.auth import get_user_model

from core.labs.models import (
    BenchGroup,
    BenchType,
    Building,
    City,
    Country,
    EquipmentCategory,
    EquipmentInterface,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    Material,
    StationType,
)
from core.labs.models.resource.base.resource import Department, Group
from core.labs.models.resource.equipment.computing import TechnicalUser
from core.labs.models.resource.equipment.display import DisplayResolution, DisplaySize
from core.labs.models.resource.equipment.networking import NetworkingProtocol
from core.labs.models.resource.equipment.sample import SampleCharacteristic, SampleCustomer

from .sheets import MAX_DATA_ROWS, SHEETS, TEMPLATE_VERSION, Column, Sheet, template_columns

_DETAIL_SHEET_BY_CATEGORY = {sheet.detail_category: sheet.name for sheet in SHEETS if sheet.detail_category}


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _limit(rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return list(rows)[:MAX_DATA_ROWS]


def _lookups() -> list[tuple[Any, ...]]:
    columns = [
        list(EquipmentInterface.objects.order_by("name").values_list("name", flat=True)),
        list(Material.objects.order_by("name").values_list("name", flat=True)),
        list(NetworkingProtocol.objects.order_by("name").values_list("name", flat=True)),
        list(SampleCustomer.objects.order_by("name").values_list("name", flat=True)),
        list(SampleCharacteristic.objects.order_by("name").values_list("name", flat=True)),
        list(TechnicalUser.objects.order_by("username").values_list("username", flat=True)),
    ]
    height = max((len(column) for column in columns), default=0)
    return [tuple(column[i] if i < len(column) else None for column in columns) for i in range(height)]


def template_rows() -> dict[str, list[tuple[Any, ...]]]:
    """Reference rows per sheet key, in the column order of ``template_columns``. Spaces and equipment stay empty."""
    users = get_user_model().objects.filter(is_active=True).order_by("username")
    rows: dict[str, list[tuple[Any, ...]]] = {
        "users": _limit(
            (user.username, user.get_full_name() or "") for user in users.only("username", "first_name", "last_name")
        ),
        "departments": _limit(Department.objects.order_by("name").values_list("name", "description", "active")),
        "groups": _limit(
            Group.objects.order_by("name").values_list("name", "department__name", "description", "active")
        ),
        "countries": _limit(Country.objects.order_by("code").values_list("code", "name")),
        "cities": _limit(City.objects.order_by("name").values_list("name", "country__name")),
        "buildings": _limit(Building.objects.order_by("name").values_list("name", "city__name", "address")),
        "station_types": _limit(StationType.objects.order_by("name").values_list("name")),
        "bench_groups": _limit(BenchGroup.objects.order_by("name").values_list("name", "description", "active")),
        "bench_types": _limit(BenchType.objects.order_by("name").values_list("name", "description", "active")),
        "screen_sizes": _limit(DisplaySize.objects.order_by("size").values_list("size", "diagonal_in")),
        "resolutions": _limit(
            DisplayResolution.objects.order_by("resolution").values_list("resolution", "width_px", "height_px")
        ),
        "lookups": _lookups(),
        "equipment_categories": _limit(
            (category.name, category.key, _DETAIL_SHEET_BY_CATEGORY.get(category.effective_key, "(none)"))
            for category in EquipmentCategory.objects.filter(active=True).order_by("name")
        ),
        "equipment_kinds": _limit(
            EquipmentKind.objects.order_by("category__name", "name").values_list("category__name", "name", "active")
        ),
        "equipment_types": _limit(
            EquipmentType.objects.order_by("kind__category__name", "kind__name", "name").values_list(
                "kind__category__name", "kind__name", "name", "active"
            )
        ),
        "product_models": _limit(
            EquipmentProductModel.objects.order_by("manufacturer__name", "name").values_list(
                "manufacturer__name",
                "equipment_type__kind__name",
                "equipment_type__name",
                "name",
                "active",
                "default_power_draw_w",
                "default_weight_kg",
            )
        ),
    }
    manufacturers = []
    for manufacturer in EquipmentManufacturer.objects.order_by("name").prefetch_related("categories"):
        names: list[str | None] = [*sorted(category.name for category in manufacturer.categories.all())[:3]]
        names += [None] * (3 - len(names))
        manufacturers.append((manufacturer.name, *names, manufacturer.active))
    rows["manufacturers"] = _limit(manufacturers)
    for key, values in rows.items():
        rows[key] = [tuple(_yes_no(v) if isinstance(v, bool) else v for v in row) for row in values]
    return rows


def template_sheets(
    data: dict[str, list[tuple[Any, ...]]] | None = None,
) -> list[tuple[Sheet, tuple[Column, ...], list[tuple[Any, ...]]]]:
    """Every declared sheet with its template columns and rows, in import order.

    Reference sheets hold the current reference data; ``data`` (the export) fills the other sheets.
    """
    rows = {**template_rows(), **(data or {})}
    return [(sheet, template_columns(sheet), rows.get(sheet.key, [])) for sheet in SHEETS]


README_ROWS: tuple[tuple[str, str], ...] = (
    ("Lab Mango - data workbook", ""),
    ("Template version", "TEMPLATE_VERSION"),
    ("", ""),
    ("How to fill", ""),
    (
        "Layout",
        "Each sheet: row 1 = title, row 2 = column names (* = required), row 3 = hint. "
        "Enter data from row 4. Do not rename sheets or columns.",
    ),
    ("Fill order", "Left to right: reference sheets (A) first, then spaces (B), then equipment (C)."),
    (
        "Existing data",
        "Reference sheets are filled with what the system already has. Keep those rows; "
        "they are matched by name and never changed. Add new values below them.",
    ),
    (
        "New or update",
        "Choose the mode when you upload. Create new (default): every asset tag must be new; one that "
        "already exists is an error. Update existing: a row whose asset tag exists updates that record, "
        "any other row is created. Rooms, stations, station slots, benches, equipment and bench placements "
        "can be updated; reference rows are only ever matched.",
    ),
    (
        "Asset tag",
        "The asset tag (SKU) identifies a record and can never be changed, in the app or by an import. "
        "To use another tag, create a new record.",
    ),
    (
        "Blank cells",
        "In update mode a blank cell keeps the stored value; an import never clears a field. "
        "Rows that match the stored record are reported as unchanged.",
    ),
    (
        "Export",
        "Export downloads this workbook filled with the current data. Edit it and upload it with "
        "Update existing. Lifecycle is left blank for equipment the import cannot set (lost, retired, "
        "transferred); blank keeps it. An open downtime is ended or changed in the app, not by an import.",
    ),
    (
        "Equipment",
        "Enter every unit once in Equipment. Category fields go into the category's detail sheet "
        "(see Equipment Categories > Detail Sheet), one row per unit, found by its asset tag.",
    ),
    (
        "Lifecycle / Condition",
        "Lifecycle says whether the lab has or runs the resource. Condition says whether "
        "it works now: In maintenance or Out of service opens a downtime from the import.",
    ),
    ("Placement", "A unit is either stored (Equipment > Storage Room) or on a bench (Bench Placements)."),
    (
        "Room slots",
        "Grid Rows and Grid Columns on a room create its slots (R1C1, R1C2 ...); stations then use those slot codes.",
    ),
    (
        "Several values",
        "Interfaces, characteristics, manufacturer categories and compatible bench types use numbered columns.",
    ),
    ("Dates", "YYYY-MM-DD, or YYYY-MM-DD hh:mm where a time is asked. Replacement Date also takes YYYY-Qn."),
    (
        "Checking",
        "Upload the file with Check first: it lists every problem by sheet, row and column and "
        "saves nothing. Apply saves everything at once, or nothing when any row has an error.",
    ),
    (
        "Not in this version",
        "Room slots by hand, specifications, licenses, purchases and costs are imported "
        "in a later version; sheets with those names are reported and skipped.",
    ),
)


def readme_rows() -> list[tuple[str, str]]:
    return [(label, TEMPLATE_VERSION if text == "TEMPLATE_VERSION" else text) for label, text in README_ROWS]


__all__ = ["README_ROWS", "readme_rows", "template_rows", "template_sheets"]
