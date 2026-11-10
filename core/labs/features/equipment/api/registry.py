"""Equipment API and model capability registry."""

from dataclasses import dataclass

from django.db.models import Model

from core.labs.features.equipment.api.capabilities import (
    ASSIGNABLE,
    AUDITABLE,
    BOOKABLE,
    LICENSABLE,
    STATUS_TRACKING,
)
from core.labs.models import Equipment
from core.labs.models.resource import equipment as equipment_models


@dataclass(frozen=True, slots=True)
class EquipmentDefinition:
    key: str
    category: str
    model: type[Model]
    display_field: str = "name"
    searchable_fields: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset({ASSIGNABLE, LICENSABLE, STATUS_TRACKING, AUDITABLE, BOOKABLE})

    @property
    def public_key(self) -> str:
        return self.key

    @property
    def search_fields(self) -> tuple[str, ...]:
        return self.searchable_fields or ("sku", "name", "serial_number", "log_label")


EQUIPMENT_REGISTRY = {
    "equipment": EquipmentDefinition(key="equipment", category="equipment", model=Equipment),
}
EQUIPMENT_API_REGISTRY = dict(EQUIPMENT_REGISTRY)

for _name in equipment_models.__all__:
    _model = getattr(equipment_models, _name)
    if isinstance(_model, type) and issubclass(_model, Equipment) and _model is not Equipment:
        _key = _model.EQUIPMENT_CATEGORY_KEY
        EQUIPMENT_REGISTRY.setdefault(_key, EquipmentDefinition(key=_key, category=_key, model=_model))
EQUIPMENT_API_REGISTRY.update(EQUIPMENT_REGISTRY)


def get_equipment_definition(equipment_type: str) -> EquipmentDefinition:
    try:
        return EQUIPMENT_API_REGISTRY[equipment_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported equipment type: {equipment_type}") from exc


def get_equipment_plugin(key: str) -> EquipmentDefinition:
    return get_equipment_definition(key)


def get_equipment_urlpatterns():
    from core.labs.features.equipment.api.urls import urlpatterns

    return urlpatterns


__all__ = (
    "EQUIPMENT_API_REGISTRY",
    "EQUIPMENT_REGISTRY",
    "EquipmentDefinition",
    "get_equipment_definition",
    "get_equipment_plugin",
    "get_equipment_urlpatterns",
)
