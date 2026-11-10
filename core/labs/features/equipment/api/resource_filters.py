"""Equipment extension of the common resource collection contract."""

from collections.abc import Sequence

from rest_framework import serializers

from core.common.api.filtering import Filter, FilterSpec, PositiveIDField, StrictBooleanField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.models import EquipmentCondition, EquipmentDisplayStatus, EquipmentLifecycleState


def equipment_filter_spec(
    search_fields: Sequence[str] = (),
    extra_filters: Sequence[Filter] = (),
    *,
    distinct_search: bool = False,
) -> FilterSpec:
    return resource_filter_spec(
        [
            Filter("category", PositiveIDField(), "kind__category_id", "reference", multiple=True),
            Filter("kind", PositiveIDField(), "kind_id", "reference", multiple=True),
            Filter("type", PositiveIDField(), "type_id", "reference", multiple=True),
            Filter("manufacturer", PositiveIDField(), "manufacturer_id", "reference", multiple=True),
            Filter("product_model_id", PositiveIDField(), "product_model_id", "reference", multiple=True),
            Filter("department_id", PositiveIDField(), "department_id", "reference", multiple=True),
            Filter("assigned", StrictBooleanField(required=False), "has_active_assignment", "boolean"),
            Filter(
                "lifecycle_state",
                serializers.ChoiceField(choices=EquipmentLifecycleState.choices),
                "lifecycle_state",
                "enum",
                multiple=True,
            ),
            Filter(
                "condition", serializers.ChoiceField(choices=EquipmentCondition.choices), "condition", "enum", multiple=True
            ),
            *extra_filters,
        ],
        search_fields=search_fields
        or (
            "sku",
            "name",
            "serial_number",
            "log_label",
            "kind__name",
            "manufacturer__name",
            "product_model__name",
        ),
        status_choices=EquipmentDisplayStatus.choices,
        status_lookup="display_status",
        distinct=distinct_search or any(item.distinct for item in extra_filters),
    )


EQUIPMENT_FILTERS = equipment_filter_spec()
