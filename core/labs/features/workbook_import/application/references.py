"""Reference sheets (departments, catalogs, lookups) and resolving names to records.

Reference rows that already exist are matched, not changed ("existing"). New rows are written through
the shared reference command (``core.reference_data.public.create_reference``), the same validated,
locked write path the reference-data API uses.
"""

from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Model

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
from core.reference_data.contracts import CreateReferenceInput, ReferenceResource
from core.reference_data.public import create_reference

from .context import ImportRun, Row, RowFailed

_LOOKUP_MODELS: dict[str, tuple[type[Model], str]] = {
    "interfaces": (EquipmentInterface, "name"),
    "materials": (Material, "name"),
    "protocols": (NetworkingProtocol, "name"),
    "customers": (SampleCustomer, "name"),
    "characteristics": (SampleCharacteristic, "name"),
    "technical_users": (TechnicalUser, "username"),
    # Template v1 kept station types in Lookups; v2 has its own sheet.
    "station_types": (StationType, "name"),
}


def _resource(model: type[Model], fields: tuple[str, ...], identity: tuple[str, ...]) -> ReferenceResource:
    # Access is checked once for the whole import (Labs administrators only).
    return ReferenceResource(
        f"workbook-import-{model._meta.model_name}", model, fields, identity, can_write=lambda actor: True
    )


class Catalog:
    """Name → primary key lookups, case-insensitive, scoped by parent where names may repeat.

    Preloads and caches each referenced model table once per import run and updates its in-memory
    index when earlier sheets create new reference or resource rows, avoiding O(rows) repeated
    SELECT queries across large workbooks.
    """

    def __init__(self, run: ImportRun) -> None:
        self.run = run
        # (model, label, scope_attrs) -> { (casefolded_label, scope_values): [pk, ...] }
        self._table_indexes: dict[tuple[type[Model], str, tuple[str, ...]], dict[tuple[Any, ...], list[int]]] = {}
        # pk -> model instance cache for objects passed into equipment commands
        self._instances: dict[tuple[type[Model], int], Any] = {}
        self._users_by_login: dict[str, tuple[int, bool]] | None = None
        self._countries_by_token: dict[str, list[int]] | None = None
        self._categories_by_token: dict[str, EquipmentCategory] | None = None

    @staticmethod
    def _scope_attr(model: type[Model], key: str) -> str:
        if key.endswith("_id"):
            return key
        try:
            field = model._meta.get_field(key)
        except Exception:  # noqa: BLE001
            return key
        return getattr(field, "attname", key)

    def _normalize_scope(self, model: type[Model], scope: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in scope.items():
            if key.endswith("__isnull"):
                field_name = key[: -len("__isnull")]
                attr = self._scope_attr(model, field_name)
                normalized[attr] = None if value else "__not_null__"
            else:
                attr = self._scope_attr(model, key)
                normalized[attr] = value.pk if isinstance(value, Model) else value
        return normalized

    def _index_for(
        self, model: type[Model], label: str, scope_attrs: tuple[str, ...]
    ) -> dict[tuple[Any, ...], list[int]]:
        cache_key = (model, label, scope_attrs)
        index = self._table_indexes.get(cache_key)
        if index is None:
            index = {}
            fields = ("pk", label, *scope_attrs)
            for row_dict in model._default_manager.values(*fields):
                raw_label = row_dict.get(label)
                if raw_label is None:
                    continue
                entry_key = (str(raw_label).casefold(), *(row_dict.get(attr) for attr in scope_attrs))
                pks = index.setdefault(entry_key, [])
                if len(pks) < 2 and row_dict["pk"] not in pks:
                    pks.append(int(row_dict["pk"]))
            self._table_indexes[cache_key] = index
        return index

    def register(self, model: type[Model], pk: int, **attrs: Any) -> None:
        """Record a newly created row in any already-loaded table indexes for ``model``."""
        norm_attrs = {self._scope_attr(model, k): (v.pk if isinstance(v, Model) else v) for k, v in attrs.items()}
        for (idx_model, label, scope_attrs), index in self._table_indexes.items():
            if idx_model is not model or label not in norm_attrs or norm_attrs[label] is None:
                continue
            if not all(attr in norm_attrs for attr in scope_attrs):
                continue
            entry_key = (str(norm_attrs[label]).casefold(), *(norm_attrs.get(attr) for attr in scope_attrs))
            pks = index.setdefault(entry_key, [])
            if pk not in pks and len(pks) < 2:
                pks.append(pk)
        if model is Country and self._countries_by_token is not None:
            for token in (norm_attrs.get("code"), norm_attrs.get("name")):
                if token:
                    pks = self._countries_by_token.setdefault(str(token).casefold(), [])
                    if pk not in pks:
                        pks.append(pk)

    def invalidate(self, model: type[Model]) -> None:
        for cache_key in [k for k in self._table_indexes if k[0] is model]:
            self._table_indexes.pop(cache_key, None)
        for inst_key in [k for k in self._instances if k[0] is model]:
            self._instances.pop(inst_key, None)

    def instance(self, model: type[Model], pk: int, *, select_related: tuple[str, ...] = ()) -> Any:
        key = (model, pk)
        found = self._instances.get(key)
        if found is None:
            qs = model._default_manager.select_related(*select_related) if select_related else model._default_manager
            found = qs.get(pk=pk)
            self._instances[key] = found
        return found

    def exists(self, model: type[Model], label: str, value: str, **scope: Any) -> bool:
        norm_scope = self._normalize_scope(model, scope)
        scope_attrs = tuple(sorted(norm_scope))
        index = self._index_for(model, label, scope_attrs)
        entry_key = (str(value).casefold(), *(norm_scope[attr] for attr in scope_attrs))
        return bool(index.get(entry_key))

    def one(self, row: Row, key: str, model: type[Model], label: str, value: str, **scope: Any) -> int:
        norm_scope = self._normalize_scope(model, scope)
        scope_attrs = tuple(sorted(norm_scope))
        index = self._index_for(model, label, scope_attrs)
        entry_key = (str(value).casefold(), *(norm_scope[attr] for attr in scope_attrs))
        matches = index.get(entry_key, [])
        if not matches:
            failed_row = self.run.failed_row(model, value)
            if failed_row is not None:
                sheet_name, number = failed_row
                raise self.run.fail(
                    row,
                    f"'{value}' is in {sheet_name} row {number}, which has errors; fix that row first.",
                    key=key,
                    code="depends_on_failed_row",
                )
            if label == "sku":
                message = (
                    f"No {model._meta.verbose_name} with asset tag '{value}' in the system or in an "
                    "earlier valid row of this file."
                )
            else:
                message = f"'{value}' was not found. Add it to its reference sheet first."
            raise self.run.fail(row, message, key=key, code="unknown_reference")
        if len(matches) > 1:
            raise self.run.fail(
                row,
                f"'{value}' matches several records; fill the column that narrows it down.",
                key=key,
                code="ambiguous_reference",
            )
        return matches[0]

    def optional(self, row: Row, key: str, model: type[Model], label: str = "name", **scope: Any) -> int | None:
        value = row.get(key)
        return None if value is None else self.one(row, key, model, label, value, **scope)

    def many(self, row: Row, key: str, model: type[Model], label: str = "name") -> list[int]:
        return [self.one(row, key, model, label, value) for value in row.get(key, [])]

    def user(self, row: Row, key: str = "owner") -> int | None:
        value = row.get(key)
        if value is None:
            return None
        if self._users_by_login is None:
            self._users_by_login = {
                str(username).casefold(): (int(pk), bool(is_active))
                for pk, username, is_active in get_user_model().objects.values_list("pk", "username", "is_active")
            }
        found = self._users_by_login.get(str(value).casefold())
        if found is None:
            raise self.run.fail(row, f"No user with the login '{value}'.", key=key, code="unknown_reference")
        pk, is_active = found
        if not is_active:
            raise self.run.fail(row, f"The user '{value}' is not active.", key=key, code="inactive_reference")
        return pk

    def user_instance(self, pk: int) -> Any:
        return self.instance(get_user_model(), pk)

    def country(self, row: Row, key: str = "country") -> int | None:
        value = row.get(key)
        if value is None:
            return None
        if self._countries_by_token is None:
            self._countries_by_token = {}
            for pk, code, name in Country.objects.values_list("pk", "code", "name"):
                for token in (code, name):
                    if token:
                        pks = self._countries_by_token.setdefault(str(token).casefold(), [])
                        if int(pk) not in pks:
                            pks.append(int(pk))
        ids = self._countries_by_token.get(str(value).casefold(), [])
        if len(ids) != 1:
            raise self.run.fail(
                row, f"Country '{value}' was not found. Add it to Countries first.", key=key, code="unknown_reference"
            )
        return ids[0]

    def category(self, row: Row, key: str = "category", value: str | None = None) -> EquipmentCategory:
        value = value if value is not None else row.get(key)
        if self._categories_by_token is None:
            self._categories_by_token = {}
            for cat in EquipmentCategory.objects.all():
                if cat.name:
                    self._categories_by_token[cat.name.casefold()] = cat
                if cat.key:
                    self._categories_by_token[cat.key.casefold()] = cat
        category = self._categories_by_token.get(str(value or "").casefold())
        if category is None:
            raise self.run.fail(
                row,
                f"Equipment category '{value}' does not exist. Categories are fixed by "
                "the system; pick one from Equipment Categories.",
                key=key,
                code="unknown_reference",
            )
        return category

    def kind(self, row: Row, *, key: str = "kind", category_key: str = "category") -> int:
        scope: dict[str, Any] = {}
        if row.get(category_key) is not None:
            scope["category"] = self.category(row, category_key)
        return self.one(row, key, EquipmentKind, "name", row.get(key), **scope)


def _digest_key(run: ImportRun, row: Row, suffix: str = "") -> str:
    raw = f"{run.file_digest}:{row.sheet.key}:{row.number}:{suffix}"
    return "workbook-" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def _create(run: ImportRun, row: Row, resource: ReferenceResource, values: dict[str, Any], suffix: str = "") -> int:
    result = create_reference(
        resource, CreateReferenceInput(values=values, idempotency_key=_digest_key(run, row, suffix)), actor=run.actor
    )
    pk = int(result.data["id"])
    run.catalog.register(resource.model, pk, **values)
    return pk


def _exists(run: ImportRun, model: type[Model], label: str, value: Any, **scope: Any) -> bool:
    return run.catalog.exists(model, label, str(value), **scope)


def _parent(field: str, pk: int | None) -> dict[str, Any]:
    return {f"{field}_id": pk} if pk is not None else {f"{field}__isnull": True}


def _active(row: Row) -> bool:
    return row.get("active", True)


def import_references(run: ImportRun) -> None:
    catalog = run.catalog

    def simple(model: type[Model], *, label: str = "name", extra: tuple[str, ...] = ()):
        fields = (label, *extra)
        resource = _resource(model, fields, (label,))

        def handler(row: Row) -> str:
            if _exists(run, model, label, row.get(label)):
                return "existing"
            values = {name: row.get(name) for name in fields if row.get(name) is not None}
            if "active" in extra:
                values["active"] = _active(row)
            _create(run, row, resource, values)
            return "created"

        return handler

    run.each("departments", simple(Department, extra=("description", "active")), natural_key="name")

    group_resource = _resource(Group, ("name", "department", "description", "active"), ("name",))

    def group(row: Row) -> str:
        if _exists(run, Group, "name", row.get("name")):
            return "existing"
        values = {"name": row.get("name"), "description": row.get("description", ""), "active": _active(row)}
        department = catalog.optional(row, "department", Department)
        if department is not None:
            values["department_id"] = department
        _create(run, row, group_resource, values)
        return "created"

    run.each("groups", group, natural_key="name")

    country_resource = _resource(Country, ("name", "code"), ("code",))

    def country(row: Row) -> str:
        if _exists(run, Country, "code", row.get("code")):
            return "existing"
        _create(run, row, country_resource, {"code": row.get("code"), "name": row.get("name")})
        return "created"

    run.each("countries", country, natural_key="code")

    city_resource = _resource(City, ("name", "country"), ("country_id", "name"))

    def city(row: Row) -> str:
        country_id = catalog.country(row)
        if _exists(run, City, "name", row.get("name"), **_parent("country", country_id)):
            return "existing"
        _create(run, row, city_resource, {"name": row.get("name"), "country_id": country_id})
        return "created"

    run.each("cities", city, natural_key="name")

    building_resource = _resource(Building, ("name", "city", "address"), ("city_id", "name"))

    def building(row: Row) -> str:
        city_id = catalog.optional(row, "city", City)
        if _exists(run, Building, "name", row.get("name"), **_parent("city", city_id)):
            return "existing"
        values = {"name": row.get("name"), "city_id": city_id, "address": row.get("address", "")}
        _create(run, row, building_resource, values)
        return "created"

    run.each("buildings", building, natural_key="name")
    run.each("station_types", simple(StationType), natural_key="name")
    run.each("bench_groups", simple(BenchGroup, extra=("description", "active")), natural_key="name")
    run.each("bench_types", simple(BenchType, extra=("description", "active")), natural_key="name")
    run.each("screen_sizes", simple(DisplaySize, label="size", extra=("diagonal_in",)), natural_key="size")
    run.each(
        "resolutions",
        simple(DisplayResolution, label="resolution", extra=("width_px", "height_px")),
        natural_key="resolution",
    )
    _import_lookups(run)

    kind_resource = _resource(EquipmentKind, ("name", "category", "active"), ("category_id", "name"))

    def kind(row: Row) -> str:
        category = catalog.category(row)
        if _exists(run, EquipmentKind, "name", row.get("name"), category_id=category.pk):
            return "existing"
        _create(run, row, kind_resource, {"name": row.get("name"), "category_id": category.pk, "active": _active(row)})
        return "created"

    run.each("equipment_kinds", kind, natural_key="__row__")

    type_resource = _resource(EquipmentType, ("name", "kind", "active"), ("kind_id", "name"))

    def equipment_type(row: Row) -> str:
        kind_id = catalog.kind(row)
        if _exists(run, EquipmentType, "name", row.get("name"), kind_id=kind_id):
            return "existing"
        _create(run, row, type_resource, {"name": row.get("name"), "kind_id": kind_id, "active": _active(row)})
        return "created"

    run.each("equipment_types", equipment_type, natural_key="__row__")

    manufacturer_resource = _resource(EquipmentManufacturer, ("name", "categories", "active"), ("name",))

    def manufacturer(row: Row) -> str:
        categories = sorted({catalog.category(row, "categories", value).pk for value in row.get("categories", [])})
        if _exists(run, EquipmentManufacturer, "name", row.get("name")):
            return "existing"
        values = {"name": row.get("name"), "categories": categories, "active": _active(row)}
        _create(run, row, manufacturer_resource, values)
        return "created"

    run.each("manufacturers", manufacturer, natural_key="name")

    model_resource = _resource(
        EquipmentProductModel,
        ("name", "manufacturer", "equipment_type", "default_power_draw_w", "default_weight_kg", "active"),
        ("manufacturer_id", "name"),
    )

    def product_model(row: Row) -> str:
        manufacturer_id = catalog.one(row, "manufacturer", EquipmentManufacturer, "name", row.get("manufacturer"))
        scope: dict[str, Any] = {}
        if row.get("kind") is not None:
            scope["kind_id"] = catalog.one(row, "kind", EquipmentKind, "name", row.get("kind"))
        type_id = catalog.one(row, "equipment_type", EquipmentType, "name", row.get("equipment_type"), **scope)
        if _exists(run, EquipmentProductModel, "name", row.get("name"), manufacturer_id=manufacturer_id):
            return "existing"
        values = {
            "name": row.get("name"),
            "manufacturer_id": manufacturer_id,
            "equipment_type_id": type_id,
            "active": _active(row),
        }
        for name in ("default_power_draw_w", "default_weight_kg"):
            if row.get(name) is not None:
                values[name] = row.get(name)
        _create(run, row, model_resource, values)
        return "created"

    run.each("product_models", product_model, natural_key="__row__")


def _import_lookups(run: ImportRun) -> None:
    """Lookups: one independent name list per column, so each cell is its own reference row."""
    bound = run.bound.get("lookups")
    if bound is None:
        return
    row_count = len(bound.rows)
    run.begin_sheet(bound.sheet.name, row_count)
    resources = {key: _resource(model, (label,), (label,)) for key, (model, label) in _LOOKUP_MODELS.items()}
    seen: dict[tuple[str, str], int] = {}
    for row in bound.rows:
        if row.failed:
            bound.outcome.failed += 1
            run.advance_row()
            continue
        for key, (model, label) in _LOOKUP_MODELS.items():
            value = row.get(key)
            if value is None:
                continue
            marker = (key, value.casefold())
            if marker in seen:
                run.row_error(row, f"Duplicate of row {seen[marker]} in this column.", key=key, code="duplicate")
                continue
            seen[marker] = row.number
            if _exists(run, model, label, value):
                bound.outcome.existing += 1
                continue
            with run.capture(row):
                _create(run, row, resources[key], {label: value}, suffix=key)
                bound.outcome.created += 1
        if row.failed:
            bound.outcome.failed += 1
        run.advance_row()
    run.finish_sheet(row_count)


__all__ = ["Catalog", "RowFailed", "import_references"]
