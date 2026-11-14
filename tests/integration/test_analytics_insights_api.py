"""Integration tests for the analytics insight endpoints (dashboard, booked-vs-used, equipment availability)."""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import BookingStatus, Equipment
from tests.factories import (
    BenchBookingFactory,
    BenchFactory,
    ComputingEquipmentFactory,
    LaboratoryVisitEventFactory,
    LabSessionLogFactory,
    ResourceDowntimeFactory,
    UserFactory,
    grant_labs_role,
)

BASE = "/api/labs/analytics"
DASHBOARD = f"{BASE}/dashboard-summary"
BOOKED_VS_USED = f"{BASE}/booked-vs-used"
EQUIPMENT_AVAILABILITY = f"{BASE}/equipment-availability"

# Fixed window so assertions are deterministic regardless of wall-clock time.
WINDOW_END = timezone.now().replace(microsecond=0)
WINDOW_START = WINDOW_END - timedelta(days=1)
QUERY = urlencode({"from_date_time": WINDOW_START.isoformat(), "to_date_time": WINDOW_END.isoformat()})


@pytest.fixture()
def auth_client(db) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory(), "coord"))
    return client


ENDPOINTS = [DASHBOARD, BOOKED_VS_USED, EQUIPMENT_AVAILABILITY]


@pytest.mark.django_db
@pytest.mark.parametrize("url", ENDPOINTS)
class TestInsightEndpointContract:
    def test_unauthenticated_is_rejected(self, url):
        resp = APIClient().get(f"{url}?{QUERY}")
        assert resp.status_code in (401, 403)

    def test_missing_range_returns_400(self, auth_client, url):
        resp = auth_client.get(url)
        assert resp.status_code == 400

    def test_unknown_query_key_returns_400(self, auth_client, url):
        resp = auth_client.get(f"{url}?{QUERY}&bogus=1")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_query"

    def test_inverted_range_returns_400(self, auth_client, url):
        inverted = urlencode({"from_date_time": WINDOW_END.isoformat(), "to_date_time": WINDOW_START.isoformat()})
        resp = auth_client.get(f"{url}?{inverted}")
        assert resp.status_code == 400

    def test_success_wraps_payload_in_data_envelope(self, auth_client, url):
        resp = auth_client.get(f"{url}?{QUERY}")
        assert resp.status_code == 200
        assert "data" in resp.json()


@pytest.mark.django_db
class TestDashboardSummary:
    def test_counts_current_and_previous_window(self, auth_client):
        # Current window: 2 visits. Previous window (same length, immediately before): 1 visit.
        LaboratoryVisitEventFactory(occurred_at=WINDOW_START + timedelta(hours=1))
        LaboratoryVisitEventFactory(occurred_at=WINDOW_START + timedelta(hours=2))
        LaboratoryVisitEventFactory(occurred_at=WINDOW_START - timedelta(hours=1))

        data = auth_client.get(f"{DASHBOARD}?{QUERY}").json()["data"]

        assert data["facility_visits"]["count"] == 2
        assert data["facility_visits"]["previous_count"] == 1
        assert data["facility_visits"]["trend_percent"] == 100

    def test_active_benches_excludes_soft_deleted(self, auth_client):
        BenchFactory()
        deleted = BenchFactory()
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])

        data = auth_client.get(f"{DASHBOARD}?{QUERY}").json()["data"]

        assert data["active_benches"]["count"] == 1

    def test_empty_window_returns_zero_counts(self, auth_client):
        data = auth_client.get(f"{DASHBOARD}?{QUERY}").json()["data"]

        assert data["bookings"]["count"] == 0
        assert data["facility_visits"]["count"] == 0
        assert data["facility_visits"]["trend_percent"] == 0


@pytest.mark.django_db
class TestBookedVsUsed:
    def test_booked_hours_clipped_to_window(self, auth_client):
        bench = BenchFactory(name="Bench A")
        # 3-hour booking starting 1 hour before the window: only 2 hours fall inside.
        BenchBookingFactory(
            bench=bench,
            starts_at=WINDOW_START - timedelta(hours=1),
            ends_at=WINDOW_START + timedelta(hours=2),
            status=BookingStatus.COMPLETED,
        )

        data = auth_client.get(f"{BOOKED_VS_USED}?{QUERY}").json()["data"]

        assert data["benches"][0]["bench"]["name"] == "Bench A"
        assert data["benches"][0]["booked_hours"] == 2.0
        assert data["total_booked_hours"] == 2.0

    def test_cancelled_and_expired_bookings_are_excluded(self, auth_client):
        bench = BenchFactory()
        start = WINDOW_START + timedelta(hours=1)
        end = WINDOW_START + timedelta(hours=2)
        BenchBookingFactory(bench=bench, starts_at=start, ends_at=end, status=BookingStatus.CANCELLED)
        BenchBookingFactory(bench=bench, starts_at=start, ends_at=end, status=BookingStatus.EXPIRED)

        data = auth_client.get(f"{BOOKED_VS_USED}?{QUERY}").json()["data"]

        assert data["benches"] == []
        assert data["total_booked_hours"] == 0.0
        assert data["used_to_booked_ratio"] is None

    def test_used_to_booked_ratio_is_capped_at_one(self, auth_client):
        bench = BenchFactory()
        BenchBookingFactory(
            bench=bench,
            starts_at=WINDOW_START + timedelta(hours=1),
            ends_at=WINDOW_START + timedelta(hours=2),
            status=BookingStatus.COMPLETED,
        )
        # Session usage far exceeds 1 booked hour.
        LabSessionLogFactory(
            login_time=WINDOW_START + timedelta(hours=1),
            logout_time=WINDOW_START + timedelta(hours=5),
            active_duration_seconds=4 * 3600,
        )

        data = auth_client.get(f"{BOOKED_VS_USED}?{QUERY}").json()["data"]

        assert data["used_to_booked_ratio"] == 1.0


@pytest.mark.django_db
class TestEquipmentAvailability:
    def test_unavailable_time_reduces_uptime(self, auth_client):
        equipment = ComputingEquipmentFactory()
        # Available for the first quarter of the window, then broken for the rest.
        quarter = (WINDOW_END - WINDOW_START) / 4
        Equipment.objects.filter(pk=equipment.pk).update(created=WINDOW_START - timedelta(hours=1))
        # Condition history is the downtime window (resource-status-and-downtime.md), still open now.
        ResourceDowntimeFactory(resource=equipment, starts_at=WINDOW_START + quarter)

        data = auth_client.get(f"{EQUIPMENT_AVAILABILITY}?{QUERY}").json()["data"]

        item = data["items"][0]
        assert item["equipment"]["id"] == equipment.pk
        assert item["outage_count"] == 1
        assert item["current_status"] == "broken"
        assert item["uptime_percent"] == 25.0

    def test_no_equipment_returns_empty_items(self, auth_client):
        data = auth_client.get(f"{EQUIPMENT_AVAILABILITY}?{QUERY}").json()["data"]

        assert data["equipment_count"] == 0
        assert data["average_uptime_percent"] is None
        assert data["items"] == []
