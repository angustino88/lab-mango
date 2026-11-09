"""Notification serializer — REST API DTO."""

from rest_framework import serializers

from core.websocket.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "message",
            "details",
            "message_type",
            "expiry_date",
            "target_user",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "target_user", "created", "modified"]
