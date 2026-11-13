"""Transport serializers shared by room and station HTTP adapters."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.labs.features.base.serializers import (
    AvailabilitySerializer,
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    ResourceWriteSerializerMixin,
    to_choice_reference,
)
from core.labs.models import (
    LegacyLocationStatus,
    ResourceAccessPolicy,
    ResourceActivityStatus,
    ResourceCondition,
    ResourceLifecycleStatus,
)
from core.labs.models.resource.base.availability import location_availability


class LocationStateFieldsMixin(serializers.Serializer):
    """Separate state fields of a room or station (design: resource-status-and-downtime.md).

    Reads annotations from ``with_location_state``; ``status`` is the deprecated seven-value field.
    """

    location_resource_type = "room"

    status = serializers.SerializerMethodField(
        help_text="Deprecated: computed from lifecycle_status, condition, access_policy and activity_status."
    )
    lifecycle_status = serializers.SerializerMethodField()
    access_policy = serializers.SerializerMethodField()
    condition = serializers.SerializerMethodField()
    availability = serializers.SerializerMethodField()
    activity_status = serializers.SerializerMethodField()

    STATE_FIELDS = ("status", "lifecycle_status", "access_policy", "condition", "availability", "activity_status")

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "legacy_status", None), LegacyLocationStatus.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_lifecycle_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.lifecycle_status, ResourceLifecycleStatus.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_access_policy(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.access_policy, ResourceAccessPolicy.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_condition(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "condition", ResourceCondition.OPERATIONAL), ResourceCondition.choices)

    @extend_schema_field(AvailabilitySerializer)
    def get_availability(self, obj) -> dict:
        return location_availability(self.location_resource_type, obj)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_activity_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(
            getattr(obj, "activity_status", ResourceActivityStatus.IDLE), ResourceActivityStatus.choices
        )


class LocationLifecycleWriteSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    lifecycle_status = serializers.ChoiceField(choices=ResourceLifecycleStatus.choices, required=False)
    access_policy = serializers.ChoiceField(choices=ResourceAccessPolicy.choices, required=False)
    metadata = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        if "lifecycle_status" not in attrs and "access_policy" not in attrs:
            raise serializers.ValidationError("Provide lifecycle_status and/or access_policy.")
        return attrs


__all__ = [
    "ChoiceReferenceSerializer",
    "LocationLifecycleWriteSerializer",
    "LocationStateFieldsMixin",
    "NamedReferenceSerializer",
]
