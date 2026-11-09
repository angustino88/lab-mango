"""HTTP category field allowlists and lookup metadata."""

from dataclasses import dataclass

from django.db import models
from rest_framework import serializers

from core.common.api.filtering import Filter


@dataclass(frozen=True)
class EquipmentCategoryAPIConfig:
    """Shared fields for each HTTP category operation with explicit overrides."""

    model: type[models.Model]
    fields: tuple[str, ...] = ()
    lookups: tuple[tuple[str, type[models.Model], str], ...] = ()
    list_fields: tuple[str, ...] | None = None
    create_fields: tuple[str, ...] | None = None
    update_fields: tuple[str, ...] | None = None
    detail_fields: tuple[str, ...] | None = None
    searchable_fields: tuple[str, ...] = ()
    list_filters: tuple[Filter, ...] = ()
    route_names: tuple[str, str, str] | None = None
    # Read-only reverse one-to-one projections shown on detail responses: (relation name, serializer).
    detail_relations: tuple[tuple[str, type[serializers.BaseSerializer]], ...] = ()

    @property
    def key(self):
        return self.model.EQUIPMENT_CATEGORY_KEY

    def fields_for(self, operation: str) -> tuple[str, ...]:
        """Use shared fields unless explicitly overridden; an empty tuple means none."""
        if operation not in {"list", "create", "update", "detail"}:
            raise ValueError(f"Unsupported category operation: {operation}")
        override = getattr(self, f"{operation}_fields")
        return self.fields if override is None else override
