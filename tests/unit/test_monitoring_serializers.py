"""Unit tests for monitoring event serializers."""
from __future__ import annotations

from unittest.mock import MagicMock

from core.labs.features.monitoring.api.serializers import (
    MonitoringEventCreateSerializer,
    MonitoringEventSerializer,
)


class TestMonitoringEventSerializer:
    def test_details_str_returns_string(self):
        obj = MagicMock()
        obj.details_str = "key: val"
        serializer = MonitoringEventSerializer()
        data = serializer.to_representation(obj)
        assert data["details_str"] == "key: val"

    def test_details_str_handles_list(self):
        obj = MagicMock()
        obj.details_str = "item1; item2"
        serializer = MonitoringEventSerializer()
        data = serializer.to_representation(obj)
        assert "item1" in data["details_str"]


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
