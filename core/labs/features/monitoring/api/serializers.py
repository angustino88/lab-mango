"""Serializers for the monitoring event HTTP API."""
from __future__ import annotations

import uuid

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.pagination import PageNumberQuerySerializer
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

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("computer_sku") and not attrs.get("computer_id"):
            raise serializers.ValidationError("Either computer_sku or computer_id must be provided.")
        return attrs


class MonitoringEventQuerySerializer(serializers.Serializer):
    computing_id = serializers.IntegerField(required=False, min_value=1)
    computer_sku = serializers.CharField(required=False)
    action = serializers.CharField(required=False)
    subject_type = serializers.CharField(required=False)
    bench_id = serializers.IntegerField(required=False)
    from_date = serializers.DateTimeField(required=False)
    to_date = serializers.DateTimeField(required=False)


class MonitoringEventListQuerySerializer(PageNumberQuerySerializer, MonitoringEventQuerySerializer):
    """Paging plus the canonical monitoring event list filters."""


__all__ = [
    "MonitoringEventListQuerySerializer",
    "MonitoringEventCreateSerializer",
    "MonitoringEventQuerySerializer",
    "MonitoringEventSerializer",
]
