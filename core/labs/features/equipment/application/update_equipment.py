"""Application commands for equipment create, update, and soft-delete writes."""

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import transaction

from core.labs.models import ComputingProfile, Equipment

from ._category import validate_category_fields
from .computing_profile import update_profile


@dataclass(frozen=True, slots=True)
class UpdateEquipmentInput:
    equipment_id: int
    fields: tuple[tuple[str, Any], ...]


@transaction.atomic
def update_equipment(command: UpdateEquipmentInput, *, actor):
    """Lock, validate, and update one equipment unit.

    Race guard: the ``Equipment`` row lock; the computing profile is written under it.
    ``computing`` holds profile changes of a monitored unit. Moving a unit into a monitored
    category creates its profile; moving a unit with a profile out of one is refused, so agents,
    activity and session logs never point at a unit that is no longer computing equipment.
    """
    instance = Equipment.objects.select_for_update(of=("self",)).select_related("kind__category").get(
        pk=command.equipment_id, deleted_at__isnull=True,
    )
    values = dict(command.fields)
    computing = values.pop("computing", None)
    _validate_fields(values)
    previous_sku = instance.sku
    previous_kind_id = instance.kind_id
    had_profile = ComputingProfile.objects.filter(equipment=instance).exists()
    many_to_many = _pop_many_to_many(values)
    for name, value in values.items():
        setattr(instance, name, value)
    kind = instance.kind
    category = kind.category
    if not kind.active or not category.active:
        raise ValidationError({"kind": "Select an active equipment kind and category."})
    if had_profile and instance.kind_id != previous_kind_id and not category.monitored:
        raise ValidationError({"kind": "A computing unit cannot move to a category that is not monitored."})
    if computing and not category.monitored:
        raise ValidationError({"computing": f"Units of the {category.name} category have no computing profile."})
    validate_category_fields(instance, category, {**values, **many_to_many})
    instance.last_modified_by = actor
    instance.full_clean()
    instance.save()
    _set_many_to_many(instance, many_to_many)
    if category.monitored and (computing or not had_profile or instance.sku != previous_sku):
        update_profile(instance, dict(computing or {}), sku_changed=instance.sku != previous_sku)
        if not had_profile:
            from core.labs.features.equipment.categories.computing.application import ensure_computing_activity

            ensure_computing_activity(instance)
    return instance


def _validate_fields(values: dict[str, Any]) -> None:
    """Reject unknown, reverse, primary-key, and command-managed fields."""
    for name in values:
        try:
            field = Equipment._meta.get_field(name)
        except FieldDoesNotExist as error:
            raise ValidationError({name: "Unknown equipment field."}) from error
        if field.primary_key or field.auto_created or field.one_to_many:
            raise ValidationError({name: "This equipment field cannot be written directly."})
        if name in {"creator", "last_modified_by", "deleted_at", "uid", "lifecycle_state", "condition"}:
            raise ValidationError({name: "This equipment field is managed by the application."})


def _pop_many_to_many(values: dict[str, Any]) -> dict[str, Any]:
    related = {}
    for name in tuple(values):
        if Equipment._meta.get_field(name).many_to_many:
            related[name] = values.pop(name)
    return related


def _set_many_to_many(instance: Equipment, related: dict[str, Any]) -> None:
    for name, values in related.items():
        getattr(instance, name).set(values)


__all__ = (
    "UpdateEquipmentInput",
    "update_equipment",
)
