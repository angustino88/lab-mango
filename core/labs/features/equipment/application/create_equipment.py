"""Create an equipment item."""

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from core.labs.models import Equipment, EquipmentKind, EquipmentLifecycleState
from core.labs.models.resource.base.resource import Department, Group

from ._category import TYPED_FIELDS, validate_category_fields
from .change_state import record_initial_lifecycle
from .computing_profile import create_profile

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
def create_equipment(command: CreateEquipmentInput, *, actor):
    """Create one equipment unit in the single equipment table.

    Shared fields are always allowed; a typed field (display size, protocol ...) only when the
    kind's category uses it (``_category.CATEGORY_TYPED_FIELDS``). ``computing`` holds the
    profile values of a unit whose category is ``monitored``; such a unit always gets a
    ``ComputingProfile``, its .rdp file and its activity record. Many-to-many values are set
    after the row is saved.
    """
    values = dict(command.fields)
    computing = values.pop("computing", None)
    unexpected = values.keys() - (SHARED_CREATE_FIELDS | TYPED_FIELDS)
    if unexpected:
        raise ValidationError({name: "Unknown or read-only field." for name in sorted(unexpected)})
    kind = _resolve_reference(EquipmentKind, values["kind"], field_name="kind")
    category = kind.category
    if not category.active:
        raise ValidationError({"kind": "Select an active equipment kind and category."})
    if computing and not category.monitored:
        raise ValidationError({"computing": f"Units of the {category.name} category have no computing profile."})
    for field_name, model_class in (("department", Department), ("group", Group)):
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
        owner = values["owner"] = get_user_model().objects.filter(pk=owner).first()
        if owner is None:
            raise ValidationError({"owner": "Select a valid reference."})
    if owner and not owner.is_active:
        raise ValidationError({"owner": "Select an active owner."})
    values["kind"] = kind
    lifecycle_state = values.get("lifecycle_state", EquipmentLifecycleState.IN_SERVICE)
    if lifecycle_state not in CREATE_LIFECYCLE_STATES:
        raise ValidationError({"lifecycle_state": "New equipment is planned or in service."})
    many_to_many = {name: values.pop(name) for name in list(values) if Equipment._meta.get_field(name).many_to_many}
    equipment = Equipment(**values, creator=actor, last_modified_by=actor)
    equipment.kind = kind
    validate_category_fields(equipment, category, {**values, **many_to_many})
    equipment.full_clean()
    equipment.save()
    for name, related in many_to_many.items():
        getattr(equipment, name).set(related)
    record_initial_lifecycle(equipment, actor=actor)
    if category.monitored:
        create_profile(equipment, dict(computing or {}))
        from core.labs.features.equipment.categories.computing.application import ensure_computing_activity

        ensure_computing_activity(equipment)
    return equipment
