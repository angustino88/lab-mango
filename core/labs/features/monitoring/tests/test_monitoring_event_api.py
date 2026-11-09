"""Tests for MonitoringEvent HTTP API and query selectors."""
from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.monitoring import public
from core.labs.models import MonitoringEvent, MonitoringEventAction
from core.users.models import User
from tests.factories import ComputingEquipmentFactory

_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"


@pytest.fixture
def computer(db):
    return ComputingEquipmentFactory(name="Station Alpha", sku="COMP-ALPHA-001")


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="monitoring_admin",
        email="admin@example.com",
        password="secret",
    )


@pytest.fixture
def auth_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
class TestMonitoringEventQueries:
    def test_list_and_get_monitoring_events(self, computer):
        now = timezone.now()
        e1 = MonitoringEvent.objects.create(
            computer=computer,
            occurred_at=now - timedelta(minutes=10),
            action=MonitoringEventAction.HEARTBEAT,
            agent_id="agent-01",
            event_id=uuid.uuid4(),
            reported_at=now,
        )
        e2 = MonitoringEvent.objects.create(
            computer=computer,
            occurred_at=now - timedelta(minutes=5),
            action=MonitoringEventAction.ALERT_RAISED,
            action_name="CPU_OVERHEAT",
            agent_id="agent-01",
            event_id=uuid.uuid4(),
            reported_at=now,
        )

        all_events = list(public.list_monitoring_events())
        assert len(all_events) == 2
        assert all_events[0] == e2  # newest first

        filtered = list(public.list_monitoring_events(action=MonitoringEventAction.ALERT_RAISED.value))
        assert len(filtered) == 1
        assert filtered[0].action_name == "CPU_OVERHEAT"

        retrieved = public.get_monitoring_event(event_id=e1.id)
        assert retrieved.id == e1.id

    def test_missing_event_raises_not_found(self):
        with pytest.raises(public.MonitoringEventNotFound):
            public.get_monitoring_event(event_id=99999)


@pytest.mark.django_db
class TestMonitoringEventCommands:
    def test_create_event_success(self, computer):
        command = public.CreateMonitoringEventInput(
            computer_sku=computer.sku,
            action=MonitoringEventAction.HEARTBEAT.value,
            payload={"cpu": 15.5},
            agent_id="agent-node-1",
        )
        event = public.create_monitoring_event(command)
        assert event.id is not None
        assert event.computer == computer
        assert event.payload == {"cpu": 15.5}

    def test_create_event_with_duplicate_id_raises_conflict(self, computer):
        event_uuid = uuid.uuid4()
        command = public.CreateMonitoringEventInput(
            computer_sku=computer.sku,
            action=MonitoringEventAction.HEARTBEAT.value,
            agent_id="agent-node-1",
            event_id=event_uuid,
        )
        public.create_monitoring_event(command)

        with pytest.raises(public.MonitoringEventConflict):
            public.create_monitoring_event(command)


@pytest.mark.django_db
class TestMonitoringEventAPI:
    def test_unauthenticated_rejected(self):
        client = APIClient()
        with patch(_PATCH_APIKEY, return_value=False):
            response = client.get("/api/labs/monitoring-events")
            assert response.status_code in (401, 403)

    def test_list_monitoring_events_endpoint(self, auth_client, computer):
        now = timezone.now()
        MonitoringEvent.objects.create(
            computer=computer,
            occurred_at=now,
            action=MonitoringEventAction.HEARTBEAT,
            agent_id="agent-01",
            event_id=uuid.uuid4(),
            reported_at=now,
        )

        response = auth_client.get("/api/labs/monitoring-events")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["action"] == "heartbeat"

    def test_create_monitoring_event_endpoint(self, auth_client, computer):
        payload = {
            "computer_sku": computer.sku,
            "action": "device_inserted",
            "subject_type": "usb_device",
            "subject_name": "Flash Drive",
            "payload": {"vendor_id": "0x1234"},
        }
        response = auth_client.post("/api/labs/monitoring-events", payload, format="json")
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["action"] == "device_inserted"
        assert data["subject_type"] == "usb_device"

    def test_retrieve_event_detail_endpoint(self, auth_client, computer):
        now = timezone.now()
        event = MonitoringEvent.objects.create(
            computer=computer,
            occurred_at=now,
            action=MonitoringEventAction.HEARTBEAT,
            agent_id="agent-01",
            event_id=uuid.uuid4(),
            reported_at=now,
        )
        response = auth_client.get(f"/api/labs/monitoring-events/{event.id}")
        assert response.status_code == 200
        assert response.json()["data"]["id"] == event.id

    def test_export_monitoring_events_endpoint(self, auth_client, computer):
        now = timezone.now()
        MonitoringEvent.objects.create(
            computer=computer,
            occurred_at=now,
            action=MonitoringEventAction.HEARTBEAT,
            agent_id="agent-01",
            event_id=uuid.uuid4(),
            reported_at=now,
        )
        response = auth_client.get("/api/labs/monitoring-events/export")
        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)
        assert len(data) == 1

    def test_legacy_lab_monitoring_alias(self, auth_client, computer):
        response = auth_client.get("/api/labs/lab-monitoring")
        assert response.status_code == 200

    def test_create_missing_computer_returns_404(self, auth_client):
        payload = {
            "computer_sku": "NONEXISTENT-SKU-9999",
            "action": "heartbeat",
        }
        response = auth_client.post("/api/labs/monitoring-events", payload, format="json")
        assert response.status_code == 404
