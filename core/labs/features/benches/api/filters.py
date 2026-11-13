"""Bench extension: lifecycle, condition, activity and actor-scoped favorites stay distinct.

``status`` filters the deprecated four-value status (computed, RS3); new clients use the separate filters.
"""

from rest_framework import serializers

from core.common.api.filtering import Filter, PositiveIDField, StrictBooleanField
from core.labs.features.base.resource_filters import resource_filter_spec
from core.labs.models import ResourceActivityStatus, ResourceCondition, ResourceLifecycleStatus
from core.labs.models.resource.base.availability import LEGACY_BENCH_STATUSES

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
    status_choices=LEGACY_BENCH_STATUSES,
    status_lookup="legacy_status",
)
