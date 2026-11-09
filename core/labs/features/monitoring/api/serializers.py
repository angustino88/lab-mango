"""Serializers for the monitoring event HTTP API."""
from __future__ import annotations

import uuid

from rest_framework import serializers

from core.labs.models.monitoring.monitoring import MonitoringEventAction


class MonitoringBenchMinimalSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    sku = serializers.CharField(read_only=True)
    bench_name = serializers.CharField(source="name", read_only=True)


class MonitoringEventSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    computer_id = serializers.IntegerField(read_only=True)
    computer_name = serializers.CharField(read_only=True)
    bench = MonitoringBenchMinimalSerializer(read_only=True, allow_null=True)
    agent_id = serializers.CharField(read_only=True)
    agent_version = serializers.CharField(read_only=True, allow_blank=True)
    event_id = serializers.UUIDField(read_only=True)
    reported_at = serializers.DateTimeField(read_only=True)
    occurred_at = serializers.DateTimeField(read_only=True)
    action = serializers.CharField(read_only=True)
    action_name = serializers.CharField(read_only=True, allow_blank=True)
    subject_type = serializers.CharField(read_only=True, allow_blank=True)
    subject_id = serializers.CharField(read_only=True, allow_blank=True)
    subject_name = serializers.CharField(read_only=True, allow_blank=True)
    payload = serializers.JSONField(read_only=True)

    # Compatibility fields
    source = serializers.CharField(source="agent_id", read_only=True)
    event_type = serializers.CharField(source="action", read_only=True)
    category = serializers.CharField(source="subject_type", read_only=True)
    object_name = serializers.CharField(source="subject_name", read_only=True)
    object_id = serializers.CharField(source="subject_id", read_only=True)
    details = serializers.JSONField(source="payload", read_only=True)
    details_str = serializers.CharField(read_only=True)
    technical_user = serializers.CharField(read_only=True, allow_blank=True, default="")
    remote_user = serializers.CharField(read_only=True, allow_blank=True, default="")
    remote_user_displayname = serializers.CharField(read_only=True, allow_blank=True, default="")
    created = serializers.DateTimeField(source="occurred_at", read_only=True)
    modified = serializers.DateTimeField(source="reported_at", read_only=True)


class MonitoringEventCreateSerializer(serializers.Serializer):
    computer_sku = serializers.CharField(required=False, allow_null=True)
    computer_id = serializers.IntegerField(required=False, allow_null=True)
    action = serializers.ChoiceField(
        choices=MonitoringEventAction.choices,
        required=False,
        default=MonitoringEventAction.HEARTBEAT.value,
    )
    action_name = serializers.CharField(required=False, allow_blank=True, default="")
    subject_type = serializers.CharField(required=False, allow_blank=True, default="")
    subject_id = serializers.CharField(required=False, allow_blank=True, default="")
    subject_name = serializers.CharField(required=False, allow_blank=True, default="")
    payload = serializers.JSONField(required=False, default=dict)
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    agent_id = serializers.CharField(required=False, default="agent")
    agent_version = serializers.CharField(required=False, allow_blank=True, default="")
    event_id = serializers.UUIDField(required=False, default=uuid.uuid4)

    # Compatibility write fields
    source = serializers.CharField(required=False, allow_blank=True)
    event_type = serializers.CharField(required=False, allow_blank=True)
    category = serializers.CharField(required=False, allow_blank=True)
    object_name = serializers.CharField(required=False, allow_blank=True)
    object_id = serializers.CharField(required=False, allow_blank=True)
    details = serializers.JSONField(required=False)

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("computer_sku") and not attrs.get("computer_id"):
            raise serializers.ValidationError("Either computer_sku or computer_id must be provided.")
        if "source" in attrs and "agent_id" not in attrs:
            attrs["agent_id"] = attrs.pop("source")
        if "event_type" in attrs:
            raw_action = attrs.pop("event_type")
            if raw_action in MonitoringEventAction.values:
                attrs["action"] = raw_action
            else:
                attrs["action"] = MonitoringEventAction.CUSTOM.value
                attrs["action_name"] = raw_action
        if "category" in attrs:
            attrs["subject_type"] = attrs.pop("category")
        if "object_name" in attrs:
            attrs["subject_name"] = attrs.pop("object_name")
        if "object_id" in attrs:
            attrs["subject_id"] = attrs.pop("object_id")
        if "details" in attrs:
            attrs["payload"] = attrs.pop("details")
        return attrs


class MonitoringEventQuerySerializer(serializers.Serializer):
    computer_id = serializers.IntegerField(required=False)
    computer_sku = serializers.CharField(required=False)
    action = serializers.CharField(required=False)
    subject_type = serializers.CharField(required=False)
    bench_id = serializers.IntegerField(required=False)
    lab = serializers.IntegerField(required=False)
    from_date = serializers.DateTimeField(required=False)
    to_date = serializers.DateTimeField(required=False)
    from_date_time = serializers.DateTimeField(required=False)
    to_date_time = serializers.DateTimeField(required=False)


__all__ = [
    "MonitoringBenchMinimalSerializer",
    "MonitoringEventCreateSerializer",
    "MonitoringEventQuerySerializer",
    "MonitoringEventSerializer",
]
