"""Category rules shared by the equipment write commands (redesign step 6, decision A).

All equipment lives in one table. The category of a unit comes only from ``kind.category``;
it decides which typed columns the unit may carry and which capabilities it has.
"""

from typing import Any

from django.core.exceptions import ValidationError

from core.labs.models import Equipment, EquipmentCategory

# Typed columns on ``Equipment`` and the built-in categories that use them. A category not
# listed here (including one created at runtime) uses none of them.
CATEGORY_TYPED_FIELDS: dict[str, tuple[str, ...]] = {
    "computing": ("mac_address",),
    "display": ("size", "resolution", "interfaces"),
    "furniture": ("dimensions", "material"),
    "instrument": ("interfaces",),
    "mechanical": ("dimensions", "material"),
    "networking": ("protocol", "mac_address"),
    "power": ("channels", "interfaces", "power_rating"),
    "sample": ("customer", "interfaces", "characteristics"),
}
TYPED_FIELDS: frozenset[str] = frozenset(name for names in CATEGORY_TYPED_FIELDS.values() for name in names)


def typed_fields_for(category: EquipmentCategory) -> tuple[str, ...]:
    return CATEGORY_TYPED_FIELDS.get(category.effective_key, ())


def _is_empty(instance: Equipment, name: str) -> bool:
    field = Equipment._meta.get_field(name)
    if field.many_to_many:
        return instance.pk is None or not getattr(instance, name).exists()
    value = getattr(instance, name)
    return value in (None, "", {}, [])


def validate_category_fields(instance: Equipment, category: EquipmentCategory, written: dict[str, Any]) -> None:
    """Refuse typed columns the category does not use, and calibration where it cannot apply.

    ``written`` holds the values of this write. A stored value the new category does not use is
    refused too, so moving a unit to another category never hides data silently.
    """
    allowed = set(typed_fields_for(category))
    errors: dict[str, str] = {}
    for name in sorted(TYPED_FIELDS - allowed):
        if name in written:
            value = written[name]
            if value not in (None, "", {}, [], ()):
                errors[name] = f"Not used by the {category.name} category."
        elif not _is_empty(instance, name):
            errors[name] = f"Clear this field before moving the unit to the {category.name} category."
    if instance.calibration_required and not category.calibratable:
        errors["calibration_required"] = f"Units of the {category.name} category are not calibrated."
    if errors:
        raise ValidationError(errors)


__all__ = ("CATEGORY_TYPED_FIELDS", "TYPED_FIELDS", "typed_fields_for", "validate_category_fields")
