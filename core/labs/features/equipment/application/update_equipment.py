"""Application commands for equipment create, update, and soft-delete writes."""

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import transaction

from core.labs.models import Equipment

from ._validation import validate_equipment_model


@dataclass(frozen=True, slots=True)
class UpdateEquipmentInput:
    equipment_id: int
    model: type[Equipment]
    fields: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DeleteEquipmentInput:
    equipment_id: int
    model: type[Equipment]


@transaction.atomic
def update_equipment(command: UpdateEquipmentInput, *, actor):
    """Lock, validate, and update one equipment model."""
    validate_equipment_model(command.model)
    instance = command.model.objects.select_for_update().get(
        pk=command.equipment_id, deleted_at__isnull=True,
    )
    values = dict(command.fields)
    _validate_fields(command.model, values)
    many_to_many = _pop_many_to_many(command.model, values)
    for name, value in values.items():
        setattr(instance, name, value)
    kind = instance.kind
    if not kind.active or not kind.category.active:
        raise ValidationError({"kind": "Select an active equipment kind and category."})
    expected_category = getattr(command.model, "EQUIPMENT_CATEGORY_KEY", "equipment")
    if expected_category != "equipment" and kind.category.effective_key != expected_category:
        raise ValidationError({"kind": "The equipment kind must match the equipment category."})
    instance.last_modified_by = actor
    instance.full_clean()
    instance.save()
    _set_many_to_many(instance, many_to_many)
    return instance


def _validate_fields(model: type[Equipment], values: dict[str, Any]) -> None:
    """Reject unknown, reverse, primary-key, and command-managed fields."""
    for name in values:
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist as error:
            raise ValidationError({name: "Unknown equipment field."}) from error
        if field.primary_key or field.auto_created or field.one_to_many:
            raise ValidationError({name: "This equipment field cannot be written directly."})
        if name in {"creator", "last_modified_by", "deleted_at", "uid"}:
            raise ValidationError({name: "This equipment field is managed by the application."})


def _pop_many_to_many(model: type[Equipment], values: dict[str, Any]) -> dict[str, Any]:
    related = {}
    for name in tuple(values):
        if model._meta.get_field(name).many_to_many:
            related[name] = values.pop(name)
    return related


def _set_many_to_many(instance: Equipment, related: dict[str, Any]) -> None:
    for name, values in related.items():
        getattr(instance, name).set(values)


__all__ = (
    "UpdateEquipmentInput",
    "update_equipment",
)
