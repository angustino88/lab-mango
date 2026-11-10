"""Create an equipment item."""

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from core.labs.models import Equipment, EquipmentKind, EquipmentLifecycleState
from core.labs.models.resource.base.resource import Department, ResourceGroup

from .change_state import record_initial_lifecycle

CREATE_LIFECYCLE_STATES = frozenset({EquipmentLifecycleState.PLANNED, EquipmentLifecycleState.IN_SERVICE})


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


def _category_models() -> dict[str, type[Equipment]]:
    """Map each concrete equipment subtype's category key to its model."""
    found: dict[str, type[Equipment]] = {}
    pending = list(Equipment.__subclasses__())
    while pending:
        subtype = pending.pop()
        pending.extend(subtype.__subclasses__())
        if not subtype._meta.abstract and not subtype._meta.proxy:
            found.setdefault(subtype.EQUIPMENT_CATEGORY_KEY, subtype)
    return found


# Shared ``Equipment`` columns every create route accepts (the create serializers' field set).
SHARED_CREATE_FIELDS = frozenset(
    {
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
        "firmware_version",
        "power_draw_w",
        "weight_kg",
        "warranty_until",
        "calibration_required",
        "lifecycle_state",
    }
)


@dataclass(frozen=True, slots=True)
class CreateEquipmentInput:
    fields: tuple[tuple[str, Any], ...]


@transaction.atomic
def create_equipment(command: CreateEquipmentInput, *, actor, model=Equipment, category_fields=frozenset()):
    """Create equipment; ``category_fields`` are the category's declared create fields.

    Shared fields are always allowed. A category endpoint passes its own create fields
    (e.g. computing ``mac_address``/``hostname``); before, they were advertised by the API
    but rejected here. Many-to-many values are set after the row is saved.

    The generic route passes the base ``Equipment`` model. The row is then created as the
    subtype registered for the kind's category, so it is visible to that category's endpoints
    (and a computing unit gets its activity record). A category with no subtype, such as one
    created at runtime, keeps a base ``Equipment`` row.
    """
    values = dict(command.fields)
    allowed_fields = set(category_fields) | SHARED_CREATE_FIELDS
    unexpected = values.keys() - allowed_fields
    if unexpected:
        raise ValidationError({name: "Unknown or read-only field." for name in sorted(unexpected)})
    kind = _resolve_reference(EquipmentKind, values["kind"], field_name="kind")
    if not kind.category.active:
        raise ValidationError({"kind": "Select an active equipment kind and category."})
    for field_name, model_class in (("department", Department), ("group", ResourceGroup)):
        if field_name in values:
            values[field_name] = _resolve_reference(model_class, values[field_name], field_name=field_name)
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
    if owner is not None and not isinstance(owner, get_user_model()):
        # The generic route sends ids; category routes send instances.
        owner = values["owner"] = get_user_model().objects.filter(pk=owner).first()
        if owner is None:
            raise ValidationError({"owner": "Select a valid reference."})
    if owner and not owner.is_active:
        raise ValidationError({"owner": "Select an active owner."})
    values["kind"] = kind
    lifecycle_state = values.get("lifecycle_state", EquipmentLifecycleState.IN_SERVICE)
    if lifecycle_state not in CREATE_LIFECYCLE_STATES:
        raise ValidationError({"lifecycle_state": "New equipment is planned or in service."})
    if not issubclass(model, Equipment):
        raise TypeError("Equipment creation requires an Equipment model subtype.")
    if model is Equipment:
        model = _category_models().get(kind.category.effective_key, Equipment)
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
    record_initial_lifecycle(equipment, actor=actor)
    if expected_category == "computing":
        from core.labs.features.equipment.categories.computing.application import ensure_computing_activity

        ensure_computing_activity(equipment)
    return equipment
