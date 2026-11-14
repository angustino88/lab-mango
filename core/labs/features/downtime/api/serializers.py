"""Downtime request and response payloads; serializers never save models."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.summary_serializers import UserReferenceSerializer
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    ResourceWriteSerializerMixin,
    to_choice_reference,
)
from core.labs.features.downtime.application.targets import RESOURCE_MODELS
from core.labs.features.downtime.queries import STATES, resource_type_of, state_of
from core.labs.models import DowntimeKind, DowntimeReason, ResourceCondition, ResourceDowntime
from core.labs.models.resource.base.downtime import DOWNTIME_CONDITIONS

DOWNTIME_CONDITION_CHOICES = [(value, ResourceCondition(value).label) for value in DOWNTIME_CONDITIONS]


class DowntimeResourceSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=tuple(RESOURCE_MODELS), read_only=True)
    id = serializers.IntegerField(read_only=True)

    class Meta:
        ref_name = "LabsDowntimeResource"


class DowntimeSerializer(AppModelSerializer):
    resource = serializers.SerializerMethodField()
    condition = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    actor = UserReferenceSerializer(source="creator", read_only=True, allow_null=True)
    ended_by = UserReferenceSerializer(read_only=True, allow_null=True)

    class Meta:
        model = ResourceDowntime
        fields = (
            "id",
            "resource",
            "condition",
            "kind",
            "reason",
            "state",
            "starts_at",
            "ends_at",
            "cancelled_at",
            "notes",
            "actor",
            "ended_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(DowntimeResourceSerializer)
    def get_resource(self, obj) -> dict:
        return {"type": resource_type_of(obj), "id": int(obj.resource_object_id)}

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_condition(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.condition, ResourceCondition.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_kind(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.kind, DowntimeKind.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_reason(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.reason, DowntimeReason.choices)

    @extend_schema_field(serializers.ChoiceField(choices=STATES))
    def get_state(self, obj) -> str:
        return state_of(obj)


class DowntimeCreateSerializer(ResourceWriteSerializerMixin, serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=tuple(RESOURCE_MODELS))
    resource_id = serializers.IntegerField(min_value=1)
    condition = serializers.ChoiceField(choices=DOWNTIME_CONDITION_CHOICES)
    reason = serializers.ChoiceField(choices=DowntimeReason.choices, required=False, default=DowntimeReason.OTHER)
    kind = serializers.ChoiceField(
        choices=DowntimeKind.choices,
        required=False,
        allow_null=True,
        default=None,
        help_text="Defaults to planned for a window that starts later, otherwise unplanned.",
    )
    starts_at = serializers.DateTimeField(required=False, allow_null=True, default=None, help_text="Default: now.")
    ends_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None, help_text="Empty while the end is not known."
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    cancel_conflicting_bookings = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Cancel reserved and in-progress bookings that overlap the window, in the same transaction.",
    )


class DowntimeListQuerySerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=tuple(RESOURCE_MODELS), required=False)
    resource_id = serializers.IntegerField(min_value=1, required=False)
    state = serializers.ChoiceField(choices=STATES, required=False)

    def validate(self, attrs):
        if "resource_id" in attrs and "resource_type" not in attrs:
            raise serializers.ValidationError({"resource_type": "Give resource_type with resource_id."})
        return attrs


__all__ = ["DowntimeCreateSerializer", "DowntimeListQuerySerializer", "DowntimeSerializer"]
