"""Request and response serializers for agent HTTP endpoints."""

from rest_framework import serializers

from core.agents.models import AgentIdentity


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


class AgentInfoResponseDataSerializer(serializers.Serializer):
    backend_id = serializers.CharField()
    server_time = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())


class AgentInfoResponseSerializer(serializers.Serializer):
    data = AgentInfoResponseDataSerializer()
