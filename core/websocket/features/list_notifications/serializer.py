"""Notification serializer — REST API DTO."""

from rest_framework import serializers

from core.common.api.summary_serializers import UserReferenceSerializer, choice_field
from core.websocket.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read shape (RW-1, ENU-1, NAM-3, REL-3)."""

    message_type = choice_field(Notification._meta.get_field("message_type").choices)
    expires_at = serializers.DateTimeField(source="expiry_date", read_only=True)
    target_user = UserReferenceSerializer(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(source="created", read_only=True)
    updated_at = serializers.DateTimeField(source="modified", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "message",
            "details",
            "message_type",
            "expires_at",
            "target_user",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class NotificationWriteSerializer(serializers.ModelSerializer):
    """Write shape (RW-1); the target user is not writable here."""

    expires_at = serializers.DateTimeField(source="expiry_date")

    class Meta:
        model = Notification
        fields = ["message", "details", "message_type", "expires_at"]
