"""Unit tests for monitoring event commands."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from core.labs.features.monitoring.application.commands import (
    CreateMonitoringEventInput,
    create_monitoring_event,
)
from core.labs.features.monitoring.exceptions import ComputerNotFound
from core.labs.models.resource.equipment.computing import ComputingEquipment


@pytest.mark.django_db
class TestCreateMonitoringEvent:
    def test_missing_computer_raises_not_found(self):
        with patch("core.labs.models.resource.equipment.computing.ComputingEquipment.objects") as mock_objects:
            mock_filter = MagicMock()
            mock_filter.first.return_value = None
            mock_objects.filter.return_value = mock_filter

            command = CreateMonitoringEventInput(computer_sku="MISSING-PC")
            with pytest.raises(ComputerNotFound):
                create_monitoring_event(command)

    def test_create_event_success(self):
        with patch("core.labs.models.resource.equipment.computing.ComputingEquipment.objects") as mock_objects:
            mock_computer = ComputingEquipment(id=1, sku="COMP-1", name="COMP-1")
            mock_filter = MagicMock()
            mock_filter.first.return_value = mock_computer
            mock_objects.filter.return_value = mock_filter

            with patch("core.labs.models.MonitoringEvent.full_clean") as mock_clean, \
                 patch("core.labs.models.MonitoringEvent.save") as mock_save:
                event_id = uuid.uuid4()
                command = CreateMonitoringEventInput(
                    computer_sku="COMP-1",
                    action="heartbeat",
                    event_id=event_id,
                )
                event = create_monitoring_event(command)

                assert event.computer == mock_computer
                assert event.action == "heartbeat"
                assert event.event_id == event_id
                mock_clean.assert_called_once()
                mock_save.assert_called_once()
