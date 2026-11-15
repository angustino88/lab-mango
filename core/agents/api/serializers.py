"""Request and response serializers for agent HTTP endpoints."""

import math

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.agents.models import AgentIdentity
from core.common.api.summary_serializers import choice_field
from core.common.api.wire_names import relation_object
from core.labs.features.base.serializers import NamedReferenceSerializer
from core.labs.models import ComputingActivityStatus, SessionAccessType


class AgentIdentitySerializer(serializers.ModelSerializer):
    equipment = serializers.SerializerMethodField()  # REL-3, REL-4
    state = choice_field(AgentIdentity._meta.get_field("state").choices)
    key_algorithm = choice_field(AgentIdentity._meta.get_field("key_algorithm").choices, allow_null=True)
    key_storage = choice_field(AgentIdentity._meta.get_field("key_storage").choices, allow_null=True)
    created_at = serializers.DateTimeField(source="created", read_only=True)
    updated_at = serializers.DateTimeField(source="modified", read_only=True)

    class Meta:
        model = AgentIdentity
        fields = [
            "id",
            "agent_uid",
            "equipment",
            "state",
            "key_algorithm",
            "key_storage",
            "fingerprint",
            "agent_version",
            "last_seen_at",
            "enrolled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_equipment(self, obj) -> dict | None:
        return relation_object(obj.equipment)


class AgentDetailResponseSerializer(serializers.Serializer):
    data = AgentIdentitySerializer()


class PaginationMetaSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)


class AgentListMetaSerializer(serializers.Serializer):
    pagination = PaginationMetaSerializer()


class AgentListResponseSerializer(serializers.Serializer):
    data = serializers.ListField(child=AgentIdentitySerializer())
    meta = AgentListMetaSerializer()


class CreateAgentGrantRequestSerializer(serializers.Serializer):
    equipment_uid = serializers.UUIDField(required=True)
    ttl_minutes = serializers.IntegerField(required=False, default=15, min_value=1, max_value=60)


class EnrollmentGrantIssuedSerializer(serializers.Serializer):
    agent_uid = serializers.UUIDField()
    equipment_uid = serializers.UUIDField()
    grant = serializers.CharField()
    expires_at = serializers.DateTimeField()


class EnrollmentGrantIssuedResponseSerializer(serializers.Serializer):
    data = EnrollmentGrantIssuedSerializer()


class CreateGrantForAgentRequestSerializer(serializers.Serializer):
    ttl_minutes = serializers.IntegerField(required=False, default=15, min_value=1, max_value=60)


class EnrollAgentRequestSerializer(serializers.Serializer):
    grant = serializers.CharField(required=True)
    public_key = serializers.CharField(required=True)
    key_storage = serializers.ChoiceField(choices=AgentIdentity.KeyStorage.choices, required=True)
    fingerprint = serializers.CharField(max_length=128, required=False, default="", allow_blank=True)
    agent_version = serializers.CharField(max_length=64, required=True)
    proof = serializers.CharField(required=True)


class AgentHeartbeatRequestSerializer(serializers.Serializer):
    # Optional echo of X-Agent-Id kept for compatibility; the signed headers are authoritative.
    agent_uid = serializers.UUIDField(required=False)


class AgentHeartbeatResponseDataSerializer(serializers.Serializer):
    status = serializers.CharField()
    last_seen_at = serializers.DateTimeField()


class AgentHeartbeatResponseSerializer(serializers.Serializer):
    data = AgentHeartbeatResponseDataSerializer()


class AgentActivityReportSerializer(serializers.Serializer):
    """Live activity the agent observes on its own computer. Timestamps and counters are server-managed."""

    status = serializers.ChoiceField(choices=ComputingActivityStatus.choices, required=False)
    remote_user = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remote_user_display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remote_computer = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remote_ip = serializers.IPAddressField(required=False, allow_null=True)
    booking_code = serializers.CharField(max_length=255, required=False, allow_blank=True)


class AgentActivityDataSerializer(serializers.Serializer):
    status = choice_field(ComputingActivityStatus.choices)
    remote_user = serializers.CharField(allow_blank=True)
    remote_user_display_name = serializers.CharField(allow_blank=True)
    remote_computer = serializers.CharField(allow_blank=True)
    remote_ip = serializers.IPAddressField(allow_null=True)
    booking_code = serializers.CharField(allow_blank=True)
    offline_at = serializers.DateTimeField(allow_null=True)
    inactive_at = serializers.DateTimeField(allow_null=True)
    last_agent_report_at = serializers.DateTimeField(allow_null=True)


class AgentActivityResponseSerializer(serializers.Serializer):
    data = AgentActivityDataSerializer()  # type: ignore[assignment]


class AgentInfoResponseDataSerializer(serializers.Serializer):
    backend_key = serializers.CharField(help_text="Logical name of this department backend (routing-sync backend_id).")
    server_time = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())
    endpoints = serializers.DictField(
        child=serializers.CharField(),
        help_text="Paths of the agent routes this backend serves, keyed by capability.",
    )


class AgentInfoResponseSerializer(serializers.Serializer):
    data = AgentInfoResponseDataSerializer()


class AgentSessionLogReportSerializer(serializers.Serializer):
    """One completed remote session, pushed once after logout. The computer is the signing agent's."""

    event_key = serializers.UUIDField(
        source="event_id", help_text="Agent-generated id of this session; repeat it on retry."
    )
    login_at = serializers.DateTimeField(source="login_time")
    logout_at = serializers.DateTimeField(source="logout_time")
    active_duration_seconds = serializers.FloatField(min_value=0)
    remote_user = serializers.CharField(max_length=255)
    remote_ip = serializers.IPAddressField(required=False, allow_null=True)
    remote_host = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    booking_code = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Empty for a temp login (no booking).",
    )
    agent_version = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate_active_duration_seconds(self, value: float) -> float:
        if not math.isfinite(value):
            raise serializers.ValidationError("Enter a finite number of seconds.")
        return value


class AgentSessionLogDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_key = serializers.UUIDField(source="event_id")
    login_at = serializers.DateTimeField(source="login_time")
    logout_at = serializers.DateTimeField(source="logout_time")
    booking_code = serializers.CharField(allow_null=True)
    # access_type: booked (a verified booking for this computer's bench), ad_hoc (no booking code),
    # unverified_booking (a code that did not verify); null only for sessions stored before access types.
    access_type = choice_field(SessionAccessType.choices, allow_null=True)


class AgentSessionLogResponseSerializer(serializers.Serializer):
    data = AgentSessionLogDataSerializer()


class AgentBookingValidationRequestSerializer(serializers.Serializer):
    booking_code = serializers.CharField(max_length=64)


class AgentBookingValidationDataSerializer(serializers.Serializer):
    is_eligible = serializers.BooleanField()
    booking_code = serializers.CharField(required=False, help_text="Present only when eligible.")
    starts_at = serializers.DateTimeField(required=False, help_text="Present only when eligible.")
    ends_at = serializers.DateTimeField(required=False, help_text="Present only when eligible.")
    booked_for = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Username the booking is for; present only when eligible.",
    )


class AgentBookingValidationResponseSerializer(serializers.Serializer):
    data = AgentBookingValidationDataSerializer()


class AgentBookingCheckInDataSerializer(serializers.Serializer):
    is_checked_in = serializers.BooleanField(help_text="True when the booking is now in progress for this login.")
    booking_code = serializers.CharField(required=False, help_text="Present only when checked in.")
    starts_at = serializers.DateTimeField(required=False, help_text="Present only when checked in.")
    ends_at = serializers.DateTimeField(required=False, help_text="Present only when checked in.")
    booked_for = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Username the booking is for; present only when checked in.",
    )


class AgentBookingCheckInResponseSerializer(serializers.Serializer):
    data = AgentBookingCheckInDataSerializer()


class AgentBookingCompleteDataSerializer(serializers.Serializer):
    is_completed = serializers.BooleanField(help_text="True when the booking is now completed.")
    booking_code = serializers.CharField(required=False, help_text="Present only when completed.")
    starts_at = serializers.DateTimeField(required=False, help_text="Present only when completed.")
    ends_at = serializers.DateTimeField(
        required=False, help_text="The booked end time, unchanged; present only when completed."
    )


class AgentBookingCompleteResponseSerializer(serializers.Serializer):
    data = AgentBookingCompleteDataSerializer()


class AgentBookingExtendRequestSerializer(serializers.Serializer):
    booking_code = serializers.CharField(max_length=64)
    ends_at = serializers.DateTimeField(help_text="The new end time. Seconds are dropped.")


class AgentBookingExtendDataSerializer(serializers.Serializer):
    is_extended = serializers.BooleanField(help_text="True when the booking now ends at ends_at.")
    booking_code = serializers.CharField(required=False, help_text="Present only when extended.")
    starts_at = serializers.DateTimeField(required=False, help_text="Present only when extended.")
    ends_at = serializers.DateTimeField(required=False, help_text="The new end; present only when extended.")


class AgentBookingExtendResponseSerializer(serializers.Serializer):
    data = AgentBookingExtendDataSerializer()




EXTENSION_REFUSAL_CODES = (
    "already_ended",
    "not_later",
    "too_short",
    "needs_approval",
    "bench_not_in_service",
    "bench_not_free",
)


@extend_schema_field(
    {
        # DOC-4: a refusal names why and the bound; a validation failure names only the field and message.
        "anyOf": [
            {
                "type": "object",
                "required": ["field", "code", "message", "limit_at"],
                "properties": {
                    "field": {"type": "string"},
                    "code": {"type": "string", "enum": list(EXTENSION_REFUSAL_CODES)},
                    "message": {"type": "string"},
                    "limit_at": {"type": "string", "format": "date-time", "nullable": True},
                },
            },
            {
                "type": "object",
                "required": ["message"],
                "properties": {"field": {"type": "string"}, "message": {"type": "string"}},
            },
        ]
    }
)
class _ExtendErrorDetailField(serializers.DictField):
    """One ``details`` item of an extension refusal or of a validation failure."""


class AgentBookingExtendErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.ListField(child=_ExtendErrorDetailField())
    request_id = serializers.CharField()


class AgentBookingExtendErrorSerializer(serializers.Serializer):
    error = AgentBookingExtendErrorBodySerializer()
