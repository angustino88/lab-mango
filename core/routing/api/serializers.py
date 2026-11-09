"""Request and response serializers for routing sync endpoints."""

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers


class ErrorDetailItemSerializer(serializers.Serializer):
    field = serializers.CharField(required=False)
    message = serializers.CharField()


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.ListField(child=ErrorDetailItemSerializer(), default=list)
    request_id = serializers.CharField()


class _ErrorBodySchemaExtension(OpenApiSerializerExtension):
    """Require response details without altering the serializer's runtime default."""

    target_class = ErrorBodySerializer

    def map_serializer(self, auto_schema, direction):
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        if direction == "response":
            schema["required"] = sorted(set(schema.get("required", [])) | {"details"})
        return schema


class ErrorEnvelopeSerializer(serializers.Serializer):
    error = ErrorBodySerializer()


class SyncStreamEntityInfoSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=0)
    epoch = serializers.UUIDField()


class SyncStreamLimitsSerializer(serializers.Serializer):
    snapshot_max_limit = serializers.IntegerField(min_value=1)
    changes_max_limit = serializers.IntegerField(min_value=1)
    longpoll_max_wait_s = serializers.IntegerField(min_value=0)


class SyncInfoResponseDataSerializer(serializers.Serializer):
    backend_id = serializers.CharField()
    server_time = serializers.CharField()
    entities = serializers.DictField(child=SyncStreamEntityInfoSerializer())
    limits = SyncStreamLimitsSerializer()


class SyncInfoResponseSerializer(serializers.Serializer):
    data = SyncInfoResponseDataSerializer()


class SnapshotQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=5000, required=False, default=1000)
    after = serializers.CharField(max_length=128, required=False, allow_blank=False)


class SnapshotItemSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=128)
    version = serializers.IntegerField(min_value=1)
    state = serializers.CharField()
    data = serializers.DictField()


class SnapshotResponseDataSerializer(serializers.Serializer):
    backend_id = serializers.CharField()
    entity_type = serializers.CharField()
    epoch = serializers.UUIDField()
    head_version = serializers.IntegerField(min_value=0)
    items = serializers.ListField(child=SnapshotItemSerializer())
    next_after = serializers.CharField(allow_null=True)


class SnapshotResponseSerializer(serializers.Serializer):
    data = SnapshotResponseDataSerializer()


class ChangesQuerySerializer(serializers.Serializer):
    since = serializers.IntegerField(min_value=0, required=True)
    epoch = serializers.UUIDField(required=True)
    limit = serializers.IntegerField(min_value=1, max_value=2000, required=False, default=500)
    wait = serializers.IntegerField(min_value=0, max_value=30, required=False, default=0)


class ChangeItemSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    op = serializers.ChoiceField(choices=["upsert", "delete"])
    key = serializers.CharField(max_length=128)
    state = serializers.CharField(required=False)
    data = serializers.DictField(required=False)


class ChangesResponseDataSerializer(serializers.Serializer):
    backend_id = serializers.CharField()
    entity_type = serializers.CharField()
    epoch = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["delta", "reset"])
    version = serializers.IntegerField(min_value=0, required=False)
    head_version = serializers.IntegerField(min_value=0)
    has_more = serializers.BooleanField(required=False)
    oldest_retained_version = serializers.IntegerField(min_value=0, required=False)
    changes = serializers.ListField(child=ChangeItemSerializer(), required=False)
    reason = serializers.CharField(required=False)


class ChangesResponseSerializer(serializers.Serializer):
    data = ChangesResponseDataSerializer()


class DigestResponseDataSerializer(serializers.Serializer):
    entity_type = serializers.CharField()
    epoch = serializers.UUIDField()
    version = serializers.IntegerField(min_value=0)
    count = serializers.IntegerField(min_value=0)
    checksum = serializers.CharField()


class DigestResponseSerializer(serializers.Serializer):
    data = DigestResponseDataSerializer()
