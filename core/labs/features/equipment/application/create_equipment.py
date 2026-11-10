"""Create an equipment item."""

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from core.labs.models import Equipment, EquipmentKind, Room
from core.labs.models.resource.base.resource import Department, ResourceGroup


def _resolve_reference(model, value, *, field_name: str):
    if value is None:
        return None
    if isinstance(value, model):
        reference = value
    else:
        try:
            reference = model.objects.get(pk=value)
        except model.DoesNotExist as error:
            raise ValidationError({field_name: "Select a valid reference."}) from error
    if not reference.active:
        raise ValidationError({field_name: "Select an active reference."})
    return reference


@dataclass(frozen=True, slots=True)
class CreateEquipmentInput:
    fields: tuple[tuple[str, Any], ...]


@transaction.atomic
def create_equipment(command: CreateEquipmentInput, *, actor, model=Equipment, category_fields=frozenset()):
    """Create equipment; ``category_fields`` are the category's declared create fields.

    Shared fields are always allowed. A category endpoint passes its own create fields
    (e.g. computing ``mac_address``/``hostname``); before, they were advertised by the API
    but rejected here. Many-to-many values are set after the row is saved.
    """
    values = dict(command.fields)
    allowed_fields = set(category_fields) | {
        "kind",
        "type",
        "manufacturer",
        "product_model",
        "sku",
        "name",
        "serial_number",
        "log_label",
        "details",
        "metadata",
        "replacement_date",
        "owner",
        "department",
        "group",
        "storage_room",
    }
    unexpected = values.keys() - allowed_fields
    if unexpected:
        raise ValidationError({name: "Unknown or read-only field." for name in sorted(unexpected)})
    kind = _resolve_reference(EquipmentKind, values["kind"], field_name="kind")
    if not kind.category.active:
        raise ValidationError({"kind": "Select an active equipment kind and category."})
    for field_name, model_class in (("department", Department), ("group", ResourceGroup)):
        if field_name in values:
            values[field_name] = _resolve_reference(model_class, values[field_name], field_name=field_name)
    if "storage_room" in values:
        values["storage_room"] = _resolve_reference(Room, values["storage_room"], field_name="storage_room")
    from core.labs import models as labs_models  # Ensure models are imported

    for field_name, model_name in (
        ("type", "EquipmentType"),
        ("manufacturer", "EquipmentManufacturer"),
        ("product_model", "EquipmentProductModel"),
    ):
        if field_name in values:
            values[field_name] = _resolve_reference(
                getattr(labs_models, model_name),
                values[field_name],
                field_name=field_name,
            )
    equipment_type = values.get("type")
    if equipment_type and equipment_type.kind_id != kind.pk:
        raise ValidationError({"type": "The equipment type must belong to the selected kind."})
    manufacturer = values.get("manufacturer")
    product_model = values.get("product_model")
    if product_model and (not manufacturer or product_model.manufacturer_id != manufacturer.pk):
        raise ValidationError({"product_model": "The product model must belong to the selected manufacturer."})
    owner = values.get("owner")
    if owner and not owner.is_active:
        raise ValidationError({"owner": "Select an active owner."})
    if not issubclass(model, Equipment):
        raise TypeError("Equipment creation requires an Equipment model subtype.")
    expected_category = getattr(model, "EQUIPMENT_CATEGORY_KEY", "equipment")
    # effective_key is the stable category code; the display name may be renamed.
    if expected_category != "equipment" and kind.category.effective_key != expected_category:
        raise ValidationError({"kind": "The equipment kind must match the equipment category."})
    many_to_many = {
        name: values.pop(name)
        for name in list(values)
        if name in category_fields and model._meta.get_field(name).many_to_many
    }
    equipment = model(**values, creator=actor, last_modified_by=actor)
    equipment.kind = kind
    equipment.full_clean()
    equipment.save()
    for name, related in many_to_many.items():
        getattr(equipment, name).set(related)
    if expected_category == "computing":
        from core.labs.features.equipment.categories.computing.application import ensure_computing_activity

        ensure_computing_activity(equipment)
    return equipment
