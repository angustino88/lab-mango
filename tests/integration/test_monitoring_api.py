"""Integration tests for monitoring event feature."""
from __future__ import annotations

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import MonitoringEvent, MonitoringEventAction
from tests.factories import (
    BenchFactory,
    ComputingEquipmentFactory,
    LabMonitoringFactory,
    UserFactory,
)


@pytest.fixture()
def monitoring_user(db):
    return UserFactory(username="monitoruser")


@pytest.fixture()
def monitoring_client(monitoring_user):
    client = APIClient()
    client.force_authenticate(user=monitoring_user)
    return client


@pytest.mark.django_db
class TestListMonitoringEvents:
    def test_unauthenticated_returns_401_or_403(self):
        client = APIClient()
        response = client.get("/api/labs/monitoring-events")
        assert response.status_code in (401, 403)

    def test_authenticated_returns_200(self, monitoring_client):
        response = monitoring_client.get("/api/labs/monitoring-events")
        assert response.status_code == 200

    def test_returns_monitoring_entries(self, monitoring_client):
        lab = BenchFactory()
        LabMonitoringFactory(bench=lab)
        response = monitoring_client.get("/api/labs/monitoring-events")
        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload
        assert len(payload["data"]) >= 1

    def test_legacy_lab_monitoring_route_returns_entries(self, monitoring_client):
        lab = BenchFactory()
        LabMonitoringFactory(bench=lab)
        response = monitoring_client.get("/api/labs/lab-monitoring")
        assert response.status_code == 200
        assert "data" in response.json()


@pytest.mark.django_db
class TestCreateMonitoringEvent:
    def test_create_heartbeat_event(self, monitoring_client):
        computer = ComputingEquipmentFactory(sku="COMP-EVENT-001")
        response = monitoring_client.post(
            "/api/labs/monitoring-events",
            {
                "computer_sku": computer.sku,
                "action": "heartbeat",
                "payload": {"status": "healthy"},
            },
            format="json",
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["action"] == "heartbeat"
        assert data["computer_id"] == computer.id

    def test_create_event_duplicate_conflict(self, monitoring_client):
        computer = ComputingEquipmentFactory(sku="COMP-EVENT-002")
        event_id = str(uuid.uuid4())
        payload = {
            "computer_sku": computer.sku,
            "action": "heartbeat",
            "agent_id": "test-agent-unique",
            "event_id": event_id,
        }
        res1 = monitoring_client.post("/api/labs/monitoring-events", payload, format="json")
        assert res1.status_code == 201

        res2 = monitoring_client.post("/api/labs/monitoring-events", payload, format="json")
        assert res2.status_code == 409

    def test_create_missing_computer_returns_404(self, monitoring_client):
        response = monitoring_client.post(
            "/api/labs/monitoring-events",
            {
                "computer_sku": "NONEXISTENT-SKU-404",
                "action": "heartbeat",
            },
            format="json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestExportMonitoringEvents:
    def test_export_monitoring_events(self, monitoring_client):
        computer = ComputingEquipmentFactory()
        MonitoringEvent.objects.create(
            computer=computer,
            action=MonitoringEventAction.HEARTBEAT,
            agent_id="agent-export",
            event_id=uuid.uuid4(),
            reported_at=timezone.now(),
            occurred_at=timezone.now(),
        )
        response = monitoring_client.get("/api/labs/monitoring-events/export")
        assert response.status_code == 200
        assert isinstance(response.json()["data"], list)
