"""Unit tests for monitoring event selectors."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.labs.features.monitoring.exceptions import MonitoringEventNotFound
from core.labs.features.monitoring.queries.selectors import (
    get_monitoring_event,
    list_monitoring_events,
)


class TestMonitoringEventSelectors:
    def test_list_monitoring_events_queries_ordered(self):
        with patch("core.labs.models.MonitoringEvent.objects") as mock_objects:
            qs_mock = MagicMock()
            mock_objects.select_related.return_value = qs_mock
            qs_mock.order_by.return_value = ["event1", "event2"]

            result = list_monitoring_events()

            mock_objects.select_related.assert_called_once_with("computer")
            qs_mock.order_by.assert_called_once_with("-occurred_at", "-id")
            assert result == ["event1", "event2"]

    def test_list_monitoring_events_filter_by_action(self):
        with patch("core.labs.models.MonitoringEvent.objects") as mock_objects:
            qs_mock = MagicMock()
            mock_objects.select_related.return_value = qs_mock
            qs_mock.filter.return_value = qs_mock
            qs_mock.order_by.return_value = []

            list_monitoring_events(action="heartbeat")

            qs_mock.filter.assert_called_once_with(action="heartbeat")

    def test_get_monitoring_event_not_found_raises(self):
        with patch("core.labs.models.MonitoringEvent.objects") as mock_objects:
            mock_filter = MagicMock()
            mock_filter.select_related.return_value.first.return_value = None
            mock_objects.filter.return_value = mock_filter

            with pytest.raises(MonitoringEventNotFound):
                get_monitoring_event(event_id=999)
