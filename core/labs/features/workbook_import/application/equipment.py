"""Equipment rows, their category detail rows, and bench placements (equipment public commands only)."""

from __future__ import annotations

from typing import Any

from django.db.models import Model

from core.labs.features.equipment.public import (
    ChangeConditionInput,
    CreateEquipmentInput,
    PlaceEquipmentInput,
    UpdateEquipmentInput,
    change_condition,
    create_equipment,
    place_equipment,
    update_equipment,
)
from core.labs.models import (
    Bench,
    Equipment,
    EquipmentInterface,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    Material,
    Room,
)
from core.labs.models.resource.base.resource import Department, Group
from core.labs.models.resource.equipment.computing import ComputingProfile, TechnicalUser
from core.labs.models.resource.equipment.display import DisplayResolution, DisplaySize
from core.labs.models.resource.equipment.networking import NetworkingProtocol
from core.labs.models.resource.equipment.sample import SampleCharacteristic, SampleCustomer

from ..queries.sheets import SHEETS
from .context import ImportRun, Row
from .references import Catalog
from .spaces import IMPORT_NOTE

DETAIL_SHEETS = tuple(sheet for sheet in SHEETS if sheet.detail_category)

# Old equipment status (template v1) → (lifecycle, condition, note, error).
_LEGACY_EQUIPMENT_STATUS: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "in use": ("in_service", None, None, None),
    "available": ("in_service", None, None, None),
    "in storage": ("in_service", None, None, None),
    "on order": ("planned", None, None, None),
    "maintenance": ("in_service", "in_maintenance", None, None),
    "broken": ("in_service", "out_of_service", None, None),
    "borrowed": (
        None,
        None,
        None,
        "Borrowed needs a loan with a borrower: import the unit as In service and record the loan in the app.",
    ),
    "transferred": (
        None,
        None,
        None,
        "Transferred units are no longer in the lab: record the transfer in the app "
        "after importing the unit as In service, or leave the unit out.",
    ),
    "lost": (None, None, None, "Lost units: import as In service, then record the loss in the app."),
}


def _status_key(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def _equipment_state(run: ImportRun, row: Row) -> tuple[str, str | None]:
    lifecycle = row.get("lifecycle_state")
    condition = row.get("condition")
    status = row.get("legacy_status")
    if status is not None and lifecycle is None and condition is None:
        mapped = _LEGACY_EQUIPMENT_STATUS.get(_status_key(status))
        if mapped is None:
            raise run.fail(
                row,
                f"Unknown status '{status}'. Use the Lifecycle and Condition columns.",
                key="legacy_status",
                code="invalid_value",
            )
        lifecycle, condition, _, error = mapped
        if error:
            raise run.fail(row, error, key="legacy_status", code="status_not_importable")
        if _status_key(status) == "in use" and row.sheet.key == "equipment":
            row.values["_expects_bench"] = True
    lifecycle = lifecycle or "in_service"
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
            computing["technical_user"] = TechnicalUser.objects.get(
                pk=catalog.one(row, "technical_user", TechnicalUser, "username", row.get("technical_user"))
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
            fields[key] = model._default_manager.get(pk=catalog.one(row, key, model, label, row.get(key)))
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


def import_equipment(run: ImportRun) -> None:
    catalog = Catalog(run)
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

    def unit(row: Row) -> str:
        lifecycle, condition = _equipment_state(run, row)
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
        technical_user = computing.pop("technical_user", None)
        if computing:
            values["computing"] = computing
        if row.get("remark") is not None:
            run.row_warning(row, "Equipment has no remarks field; put the note in Details.", key="remark")
        created = create_equipment(CreateEquipmentInput(fields=tuple(values.items())), actor=run.actor)
        if technical_user is not None:
            update_equipment(
                UpdateEquipmentInput(
                    equipment_id=created.pk, fields=(("computing", {"technical_user": technical_user}),)
                ),
                actor=run.actor,
            )
        _remember_rdp_file(run, created.pk)
        if condition is not None:
            change_condition(
                ChangeConditionInput(equipment_id=created.pk, condition=condition, reason=IMPORT_NOTE),
                actor=run.actor,
            )
        if row.get("storage_room") is not None:
            room_id = catalog.one(row, "storage_room", Room, "sku", row.get("storage_room"))
            place_equipment(PlaceEquipmentInput(equipment_id=created.pk, room_id=room_id), actor=run.actor)
            storage[row.get("sku").casefold()] = row.number
        return "created"

    run.each("equipment", unit)
    for sheet in DETAIL_SHEETS:
        bound = run.bound.get(sheet.key)
        if bound is None:
            continue
        for row in bound.rows:
            if row.failed:
                bound.outcome.failed += 1
            elif row.get("sku") and row.get("sku").casefold() in used:
                bound.outcome.created += 1

    placed: set[str] = set()

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
        place_equipment(
            PlaceEquipmentInput(
                equipment_id=equipment_id,
                bench_id=bench_id,
                role=row.get("role", "default"),
                position=row.get("position", 0),
            ),
            actor=run.actor,
        )
        placed.add(sku.casefold())
        return "created"

    run.each("bench_placements", placement, natural_key="__row__")
    for row in run.rows("equipment"):
        if row.values.get("_expects_bench") and not row.failed and row.get("sku").casefold() not in placed:
            run.row_warning(
                row,
                "Status In-use, but the unit has no row in Bench Placements.",
                key="legacy_status",
                code="status_mapped",
            )


__all__ = ["import_equipment"]
