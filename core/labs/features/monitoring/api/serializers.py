"""Serializers for the monitoring event HTTP API."""
from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.summary_serializers import choice_field
from core.common.api.wire_names import relation_object
from core.labs.features.base.serializers import NamedReferenceSerializer
from core.labs.models.monitoring.monitoring import MonitoringEventAction


class MonitoringSubjectSerializer(serializers.Serializer):
    """What the agent reported on (STR-1): agent-side identifiers, not API resources (NAM-8)."""

    type = serializers.CharField(source="subject_type", read_only=True, allow_blank=True)
    key = serializers.CharField(source="subject_id", read_only=True, allow_blank=True)
    name = serializers.CharField(source="subject_name", read_only=True, allow_blank=True)


class MonitoringEventSerializer(serializers.Serializer):
    """One event; agent identifiers end in ``_key`` (NAM-8), relations are ``{id, name}`` (REL-3)."""

    id = serializers.IntegerField(read_only=True)
    computer = serializers.SerializerMethodField()
    bench = serializers.SerializerMethodField()
    agent_key = serializers.CharField(source="agent_id", read_only=True)
    agent_version = serializers.CharField(read_only=True, allow_blank=True)
    event_key = serializers.UUIDField(source="event_id", read_only=True)
    reported_at = serializers.DateTimeField(read_only=True)
    occurred_at = serializers.DateTimeField(read_only=True)
    action = choice_field(MonitoringEventAction.choices)
    action_name = serializers.CharField(read_only=True, allow_blank=True)
    subject = MonitoringSubjectSerializer(source="*", read_only=True)
    payload = serializers.JSONField(read_only=True)
    technical_user = serializers.CharField(read_only=True, allow_blank=True, default="")
    remote_user = serializers.CharField(read_only=True, allow_blank=True, default="")
    remote_user_display_name = serializers.CharField(
        source="remote_user_displayname", read_only=True, allow_blank=True, default=""
    )

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_computer(self, obj) -> dict | None:
        return relation_object(obj.computer) if obj.computer_id else None

    @extend_schema_field(NamedReferenceSerializer(allow_null=True))
    def get_bench(self, obj) -> dict | None:
        return relation_object(obj.bench)


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
    "MonitoringEventCreateSerializer",
    "MonitoringEventQuerySerializer",
    "MonitoringEventSerializer",
]
