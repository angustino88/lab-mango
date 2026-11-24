"""Bench extension: lifecycle, condition, activity and actor-scoped favorites stay distinct."""

from rest_framework import serializers

from core.common.api.filtering import Filter, PositiveIDField, StrictBooleanField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.models import ResourceActivityStatus, ResourceCondition, ResourceLifecycleStatus

BENCH_FILTERS = resource_filter_spec(
    [
        Filter("setup_location_id", PositiveIDField(), "setup_location_id", "reference", multiple=True),
        Filter("bench_group_id", PositiveIDField(), "bench_group_id", "reference", multiple=True),
        Filter("type_id", PositiveIDField(), "type_id", "reference", multiple=True),
        Filter("favorite", StrictBooleanField(required=False), "is_favorite", "boolean"),
        Filter(
            "lifecycle_status",
            serializers.ChoiceField(choices=ResourceLifecycleStatus.choices),
            "lifecycle_status",
            "enum",
            multiple=True,
        ),
        Filter(
            "condition", serializers.ChoiceField(choices=ResourceCondition.choices), "condition", "enum", multiple=True
        ),
        Filter(
            "activity_status",
            serializers.ChoiceField(choices=ResourceActivityStatus.choices),
            "activity_status",
            "enum",
            multiple=True,
        ),
    ],
    search_fields=("sku", "name", "description"),
)
