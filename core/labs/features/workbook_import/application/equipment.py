"""Equipment rows, their category detail rows, and bench placements (equipment public commands only)."""

from __future__ import annotations

from typing import Any

from django.db.models import Model

from core.labs.features.equipment.public import (
    ChangeConditionInput,
    ChangeLifecycleInput,
    CreateEquipmentInput,
    PlaceEquipmentInput,
    UpdateEquipmentInput,
    change_condition,
    change_lifecycle,
    create_equipment,
    place_equipment,
    update_equipment,
)
from core.labs.models import (
    Bench,
    Equipment,
    EquipmentInterface,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    Material,
    Room,
)
from core.labs.models.resource.base.resource import Department, Group
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.computing import ComputingProfile, TechnicalUser
from core.labs.models.resource.equipment.display import DisplayResolution, DisplaySize
from core.labs.models.resource.equipment.networking import NetworkingProtocol
from core.labs.models.resource.equipment.sample import SampleCharacteristic, SampleCustomer

from ..queries.sheets import SHEETS
from .context import ImportRun, Row
from .references import Catalog
from .spaces import IMPORT_NOTE
from .updates import current_condition, same_value

DETAIL_SHEETS = tuple(sheet for sheet in SHEETS if sheet.detail_category)
# Values that come from a detail sheet (and the computing profile); an update writes them as given.
_DETAIL_KEYS = frozenset(
    {
        "computing",
        "mac_address",
        "size",
        "resolution",
        "material",
        "protocol",
        "customer",
        "interfaces",
        "characteristics",
        "channels",
        "power_rating",
        "dimensions",
    }
)
# Equipment row value key → model attribute holding the same id, for comparing an update with the unit.
_ID_ATTRIBUTES = {
    "kind": "kind_id",
    "type": "type_id",
    "manufacturer": "manufacturer_id",
    "product_model": "product_model_id",
    "department": "department_id",
    "group": "group_id",
    "owner": "owner_id",
}

def _equipment_state(run: ImportRun, row: Row) -> tuple[str, str | None]:
    lifecycle = row.get("lifecycle_state") or "in_service"
    condition = row.get("condition")
    if lifecycle == "planned" and condition not in (None, "operational"):
        raise run.fail(row, "A planned unit has no condition yet; leave Condition empty.", key="condition")
    return lifecycle, None if condition == "operational" else condition


def _detail_fields(run: ImportRun, catalog: Catalog, row: Row) -> tuple[dict[str, Any], dict[str, Any]]:
    """Typed fields and computing-profile values from one detail row."""
    fields: dict[str, Any] = {}
    computing: dict[str, Any] = {}
    category = row.sheet.detail_category
    if category == "computing":
        if row.get("hostname") is not None:
            computing["hostname"] = row.get("hostname")
        if row.get("technical_user") is not None:
            computing["technical_user"] = catalog.instance(
                TechnicalUser, catalog.one(row, "technical_user", TechnicalUser, "username", row.get("technical_user"))
            )
        if row.get("os_name") is not None:
            run.row_warning(
                row, "The operating system is reported by the computer agent; not imported.", key="os_name"
            )
    if row.get("mac_address") is not None:
        fields["mac_address"] = row.get("mac_address")
    lookups: tuple[tuple[str, type[Model], str], ...] = (
        ("size", DisplaySize, "size"),
        ("resolution", DisplayResolution, "resolution"),
        ("material", Material, "name"),
        ("protocol", NetworkingProtocol, "name"),
        ("customer", SampleCustomer, "name"),
    )
    for key, model, label in lookups:
        if row.get(key) is not None:
            fields[key] = catalog.instance(model, catalog.one(row, key, model, label, row.get(key)))
    for key, related in (("interfaces", EquipmentInterface), ("characteristics", SampleCharacteristic)):
        if row.get(key):
            fields[key] = catalog.many(row, key, related)
    for key in ("channels", "power_rating"):
        if row.get(key) is not None:
            fields[key] = row.get(key)
    dimensions = {key: row.get(key) for key in ("length_mm", "width_mm", "height_mm") if row.get(key) is not None}
    if dimensions:
        fields["dimensions"] = dimensions
    return fields, computing


def _remember_rdp_file(run: ImportRun, equipment_id: int) -> None:
    """Note the .rdp file a computing unit got, so a rolled-back run can delete it again."""
    field = ComputingProfile._meta.get_field("rdp_file")
    for name in ComputingProfile.objects.filter(equipment_id=equipment_id).values_list("rdp_file", flat=True):
        run.remember_file(field.storage, name)


def _remember_created_rdp_file(run: ImportRun, created: Equipment) -> None:
    """As ``_remember_rdp_file`` for a unit just created: its profile is already loaded on the unit."""
    profile = created._state.fields_cache.get("computing_profile")
    if profile is None:
        _remember_rdp_file(run, created.pk)
        return
    run.remember_file(ComputingProfile._meta.get_field("rdp_file").storage, profile.rdp_file.name or None)


def import_equipment(run: ImportRun) -> None:
    catalog = run.catalog
    details: dict[str, Row] = {}
    for sheet in DETAIL_SHEETS:
        for row in run.rows(sheet.key):
            sku = row.get("sku")
            if sku is None or row.failed:
                continue
            if sku.casefold() in details:
                other = details[sku.casefold()]
                run.row_error(
                    row,
                    f"The unit already has details in {other.sheet.name} row {other.number}.",
                    key="sku",
                    code="duplicate",
                )
                continue
            details[sku.casefold()] = row
    used: set[str] = set()
    equipment_skus = {row.get("sku").casefold() for row in run.rows("equipment") if row.get("sku")}
    for sku, detail in details.items():
        if sku not in equipment_skus:
            run.row_error(detail, "Add this unit to the Equipment sheet first.", key="sku", code="unknown_reference")

    storage: dict[str, int] = {}
    updated_details: set[str] = set()

    def unit(row: Row) -> str:
        lifecycle, condition = _equipment_state(run, row)
        existing = run.existing(Equipment, row)
        category = catalog.category(row)
        kind_id = catalog.kind(row)
        values: dict[str, Any] = {"kind": kind_id, "sku": row.get("sku"), "lifecycle_state": lifecycle}
        for key in (
            "name",
            "serial_number",
            "log_label",
            "details",
            "replacement_date",
            "firmware_version",
            "power_draw_w",
            "weight_kg",
            "warranty_until",
            "calibration_required",
        ):
            if row.get(key) is not None:
                values[key] = row.get(key)
        if row.get("type") is not None:
            values["type"] = catalog.one(row, "type", EquipmentType, "name", row.get("type"), kind_id=kind_id)
        manufacturer_id = None
        if row.get("manufacturer") is not None:
            manufacturer_id = catalog.one(row, "manufacturer", EquipmentManufacturer, "name", row.get("manufacturer"))
            values["manufacturer"] = manufacturer_id
        if row.get("product_model") is not None:
            if manufacturer_id is None:
                raise run.fail(row, "A product model needs its manufacturer.", key="product_model")
            values["product_model"] = catalog.one(
                row,
                "product_model",
                EquipmentProductModel,
                "name",
                row.get("product_model"),
                manufacturer_id=manufacturer_id,
            )
        for key, model in (("department", Department), ("group", Group)):
            if row.get(key) is not None:
                values[key] = catalog.one(row, key, model, "name", row.get(key))
        owner = catalog.user(row)
        if owner is not None:
            values["owner"] = owner
        computing: dict[str, Any] = {}
        detail = details.get(row.get("sku").casefold())
        if detail is not None:
            if detail.sheet.detail_category != category.effective_key:
                raise run.fail(
                    row,
                    f"The {category.name} category does not use the {detail.sheet.name} sheet; "
                    "move the details to the category's sheet.",
                    key="category",
                )
            used.add(row.get("sku").casefold())
            typed, computing = _detail_fields(run, catalog, detail)
            if detail.failed:
                raise run.fail(row, f"Fix the details in {detail.sheet.name} row {detail.number} first.", key="sku")
            values.update(typed)
        if row.get("remark") is not None:
            run.row_warning(row, "Equipment has no remarks field; put the note in Details.", key="remark")
        if existing is not None:
            technical_user = computing.pop("technical_user", None)
            if computing:
                values["computing"] = computing
            explicit_condition = row.get("condition")
            if (
                explicit_condition is None
                and row.get("legacy_status") is not None
                and row.get("lifecycle_state") is None
            ):
                explicit_condition = condition or "operational"
            explicit_lifecycle = row.get("lifecycle_state")
            if explicit_lifecycle is None and row.get("legacy_status") is not None:
                explicit_lifecycle = lifecycle
            return _update_unit(
                existing,
                row,
                values,
                computing=computing,
                technical_user=technical_user,
                has_detail=detail is not None,
                lifecycle=explicit_lifecycle,
                condition=explicit_condition,
            )
        if computing:
            values["computing"] = computing
        # Hand the create command cached instances so it does not re-select every reference per row.
        create_fields = dict(values)
        create_fields["kind"] = catalog.instance(EquipmentKind, kind_id, select_related=("category",))
        for ref_key, ref_model in (
            ("type", EquipmentType),
            ("manufacturer", EquipmentManufacturer),
            ("product_model", EquipmentProductModel),
            ("department", Department),
            ("group", Group),
        ):
            if ref_key in create_fields and isinstance(create_fields[ref_key], int):
                create_fields[ref_key] = catalog.instance(ref_model, create_fields[ref_key])
        if "owner" in create_fields and isinstance(create_fields["owner"], int):
            create_fields["owner"] = catalog.user_instance(create_fields["owner"])
        room_id = None
        if row.get("storage_room") is not None:
            room_id = catalog.one(row, "storage_room", Room, "sku", row.get("storage_room"))
        # The starting condition and storage room are set by the create command in the same transaction,
        # as ``change_condition`` and ``place_equipment`` would set them right after it.
        created = create_equipment(
            CreateEquipmentInput(
                fields=tuple(create_fields.items()),
                condition=condition,
                condition_reason=IMPORT_NOTE if condition is not None else "",
                room_id=room_id,
            ),
            actor=run.actor,
        )
        catalog.register(Equipment, created.pk, sku=created.sku)
        if category.monitored:
            _remember_created_rdp_file(run, created)
        if room_id is not None:
            storage[row.get("sku").casefold()] = row.number
        return "created"

    def _update_unit(
        unit: Equipment,
        row: Row,
        values: dict[str, Any],
        *,
        computing: dict[str, Any],
        technical_user: Any,
        has_detail: bool,
        lifecycle: str | None,
        condition: str | None,
    ) -> str:
        """Update one existing unit: changed general fields, detail fields, condition, lifecycle, storage."""
        values = {key: value for key, value in values.items() if key not in ("sku", "lifecycle_state")}
        general = {key: value for key, value in values.items() if key not in _DETAIL_KEYS}
        # References are written by id (``kind_id``), the form the update command can set on the row.
        changes = {
            _ID_ATTRIBUTES.get(key, key): value
            for key, value in general.items()
            if not same_value(getattr(unit, _ID_ATTRIBUTES.get(key, key), None), value)
        }
        if has_detail:
            # Detail fields (relations, many-to-many) are written as given.
            changes.update({key: value for key, value in values.items() if key in _DETAIL_KEYS - {"computing"}})
            hostname = computing.get("hostname")
            if hostname is not None:
                stored = (
                    ComputingProfile.objects.filter(equipment_id=unit.pk).values_list("hostname", flat=True).first()
                )
                if not same_value(stored, hostname):
                    run.row_warning(
                        row,
                        "The hostname is set when the unit is registered; change it in the app. Not changed.",
                        key="sku",
                        code="hostname_not_changed",
                    )
            if technical_user is not None:
                changes["computing"] = {"technical_user": technical_user}
            updated_details.add(row.get("sku").casefold())
        changed = bool(changes)
        if changes:
            update_equipment(
                UpdateEquipmentInput(equipment_id=unit.pk, fields=tuple(changes.items())), actor=run.actor
            )
            _remember_rdp_file(run, unit.pk)
        if condition is not None and condition != current_condition(unit):
            change_condition(
                ChangeConditionInput(equipment_id=unit.pk, condition=condition, reason=IMPORT_NOTE), actor=run.actor
            )
            changed = True
        if lifecycle is not None and lifecycle != unit.lifecycle_state:
            change_lifecycle(
                ChangeLifecycleInput(equipment_id=unit.pk, lifecycle_state=lifecycle, reason=IMPORT_NOTE),
                actor=run.actor,
            )
            changed = True
        if row.get("storage_room") is not None:
            room_id = catalog.one(row, "storage_room", Room, "sku", row.get("storage_room"))
            stored_in = (
                EquipmentAssignment.objects.filter(equipment_id=unit.pk, unassigned_at__isnull=True)
                .values_list("room_id", flat=True)
                .first()
            )
            if stored_in != room_id:
                place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, room_id=room_id), actor=run.actor)
                changed = True
            storage[row.get("sku").casefold()] = row.number
        return "updated" if changed else "existing"

    run.each("equipment", unit)
    for sheet in DETAIL_SHEETS:
        bound = run.bound.get(sheet.key)
        if bound is None:
            continue
        for row in bound.rows:
            if row.failed:
                bound.outcome.failed += 1
            elif row.get("sku") and row.get("sku").casefold() in updated_details:
                bound.outcome.updated += 1
            elif row.get("sku") and row.get("sku").casefold() in used:
                bound.outcome.created += 1

    placed: set[str] = set()
    active_assignments: dict[int, dict[str, Any]] | None = None

    def _active_assignment(equipment_id: int) -> dict[str, Any] | None:
        nonlocal active_assignments
        if active_assignments is None:
            active_assignments = {
                int(row_dict["equipment_id"]): row_dict
                for row_dict in EquipmentAssignment.objects.filter(unassigned_at__isnull=True).values(
                    "equipment_id", "room_id", "bench_id", "role", "position"
                )
            }
        return active_assignments.get(equipment_id)

    def placement(row: Row) -> str:
        sku = row.get("equipment")
        for key in ("assigned_on", "unassigned_on", "monitor"):
            if row.get(key) is not None:
                run.row_warning(row, "Placements start now; dates and the monitored flag are not imported.", key=key)
                break
        if sku.casefold() in storage:
            raise run.fail(
                row,
                f"The unit has a Storage Room (Equipment row {storage[sku.casefold()]}); "
                "a unit is either stored or on a bench.",
                key="equipment",
            )
        if sku.casefold() in placed:
            raise run.fail(
                row, "The unit is already placed on another bench in this sheet.", key="equipment", code="duplicate"
            )
        bench_id = catalog.one(row, "bench", Bench, "sku", row.get("bench"))
        equipment_id = catalog.one(row, "equipment", Equipment, "sku", sku)
        role, position = row.get("role", "default"), row.get("position", 0)
        current = _active_assignment(equipment_id)
        if current is not None and current["bench_id"] == bench_id:
            placed.add(sku.casefold())
            if (current["role"], current["position"]) == (role, position):
                return "existing"
            run.row_warning(
                row,
                "The unit is already on this bench; role and position are changed in the app.",
                key="role",
                code="placement_not_changed",
            )
            return "existing"
        place_equipment(
            PlaceEquipmentInput(
                equipment_id=equipment_id,
                bench_id=bench_id,
                role=role,
                position=position,
            ),
            actor=run.actor,
        )
        if active_assignments is not None:
            active_assignments[equipment_id] = {
                "equipment_id": equipment_id,
                "room_id": None,
                "bench_id": bench_id,
                "role": role,
                "position": position,
            }
        placed.add(sku.casefold())
        return "created" if current is None else "updated"

    run.each("bench_placements", placement, natural_key="__row__")


__all__ = ["import_equipment"]
