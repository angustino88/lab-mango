"""Filters shared by rooms and stations: the separate state fields (design: resource-status-and-downtime.md)."""

from rest_framework import serializers

from core.common.api.filtering import Filter
from core.labs.models import ResourceAccessPolicy, ResourceActivityStatus, ResourceCondition, ResourceLifecycleStatus


def location_state_filters() -> list[Filter]:
    """Filters over stored lifecycle and access policy and the computed condition and activity."""
    return [
        Filter(name, serializers.ChoiceField(choices=choices), name, "enum", multiple=True)
        for name, choices in (
            ("lifecycle_status", ResourceLifecycleStatus.choices),
            ("access_policy", ResourceAccessPolicy.choices),
            ("condition", ResourceCondition.choices),
            ("activity_status", ResourceActivityStatus.choices),
        )
    ]


__all__ = ["location_state_filters"]
