"""Unit tests for monitoring event serializers."""
from __future__ import annotations

from core.labs.features.monitoring.api.serializers import (
    MonitoringEventCreateSerializer,
    MonitoringEventSerializer,
)


class TestMonitoringEventSerializer:
    def _event(self):
        from core.labs.models.monitoring.monitoring import MonitoringEvent

        return MonitoringEvent(
            id=1,
            agent_id="agent-1",
            action="heartbeat",
            subject_type="usb_device",
            subject_id="usb-42",
            subject_name="Scanner",
            payload={"key": "val"},
        )

    def test_agent_subject_is_one_group_with_key_not_id(self):
        data = MonitoringEventSerializer(self._event()).data
        assert data["subject"] == {"type": "usb_device", "key": "usb-42", "name": "Scanner"}  # STR-1, NAM-8
        assert data["agent_key"] == "agent-1"
        assert data["action"] == {"value": "heartbeat", "label": "Heartbeat"}  # ENU-1

    def test_compatibility_duplicates_are_not_returned(self):
        data = MonitoringEventSerializer(self._event()).data
        removed = {"source", "event_type", "category", "object_name", "object_id", "details", "details_str"}
        assert not removed & set(data)
        assert data["payload"] == {"key": "val"}


class TestMonitoringEventCreateSerializer:
    def test_requires_computer_sku_or_id(self):
        serializer = MonitoringEventCreateSerializer(data={"action": "heartbeat"})
        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors

    def test_valid_with_sku(self):
        serializer = MonitoringEventCreateSerializer(
            data={"computer_sku": "COMP-001", "action": "heartbeat", "payload": {"cpu": 10}}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["computer_sku"] == "COMP-001"

    def test_valid_with_id(self):
        serializer = MonitoringEventCreateSerializer(
            data={"computer_id": 42, "action": "device_inserted"}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["computer_id"] == 42
