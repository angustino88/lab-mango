"""Request and response serializers for agent HTTP endpoints."""

import math

from rest_framework import serializers

from core.agents.models import AgentIdentity
from core.labs.models import ComputingActivityStatus


class AgentIdentitySerializer(serializers.ModelSerializer):
    equipment_sku = serializers.CharField(source="equipment.sku", read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", read_only=True)

    class Meta:
        model = AgentIdentity
        fields = [
            "id",
            "agent_uid",
            "equipment",
            "equipment_sku",
            "equipment_name",
            "state",
            "key_algorithm",
            "key_storage",
            "fingerprint",
            "agent_version",
            "last_seen_at",
            "enrolled_at",
            "created",
            "modified",
        ]
        read_only_fields = fields


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
    status = serializers.ChoiceField(choices=ComputingActivityStatus.choices)
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
    backend_id = serializers.CharField()
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

    event_id = serializers.UUIDField(help_text="Agent-generated id of this session; repeat it on retry.")
    login_time = serializers.DateTimeField()
    logout_time = serializers.DateTimeField()
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
    event_id = serializers.UUIDField()
    login_time = serializers.DateTimeField()
    logout_time = serializers.DateTimeField()
    booking_code = serializers.CharField(allow_null=True)


class AgentSessionLogResponseSerializer(serializers.Serializer):
    data = AgentSessionLogDataSerializer()


class AgentBookingValidationRequestSerializer(serializers.Serializer):
    booking_code = serializers.CharField(max_length=64)


class AgentBookingValidationDataSerializer(serializers.Serializer):
    eligible = serializers.BooleanField()
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
