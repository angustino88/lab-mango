"""Integration tests for analytics API endpoints — TDD red phase."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from tests.factories import (
    BenchBookingFactory,
    BenchFactory,
    BookingVolumeObservationFactory,
    ComputingEquipmentFactory,
    EquipmentStatusRecordFactory,
    LabProjectFactory,
    LabSessionLogFactory,
    StorageQuotaMeasurementFactory,
    UserFactory,
    VisitorVolumeObservationFactory,
)

BASE = "/api/labs/analytics"
NOW = timezone.now()
FROM_DT = (NOW - timedelta(days=7)).isoformat()
TO_DT = NOW.isoformat()


@pytest.fixture()
def auth_client(db) -> APIClient:
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/bench-group
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBenchGroupSummary:
    def test_unauth_returns_401_or_403(self):
        resp = APIClient().get(f"{BASE}/bench-group")
        assert resp.status_code in (401, 403)

    def test_returns_200_with_data_key(self, auth_client):
        BenchFactory()
        resp = auth_client.get(f"{BASE}/bench-group")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_response_shape(self, auth_client, db):
        BenchFactory()
        resp = auth_client.get(f"{BASE}/bench-group")
        data = resp.json()["data"]
        assert len(data) >= 1
        assert "entries" in data[0]


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/lab-equipment-status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEquipmentStatusSummary:
    def test_unauth_returns_401_or_403(self):
        resp = APIClient().get(f"{BASE}/lab-equipment-status")
        assert resp.status_code in (401, 403)

    def test_returns_200(self, auth_client):
        resp = auth_client.get(f"{BASE}/lab-equipment-status")
        assert resp.status_code == 200

    def test_data_has_status_and_entries(self, auth_client, db):
        EquipmentStatusRecordFactory(status="available")
        resp = auth_client.get(f"{BASE}/lab-equipment-status")
        data = resp.json()["data"]
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/lab-efficiency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLabEfficiency:
    def test_missing_dates_returns_400(self, auth_client):
        resp = auth_client.get(f"{BASE}/lab-efficiency")
        assert resp.status_code == 400

    def test_valid_request_returns_200(self, auth_client, db):
        comp = ComputingEquipmentFactory()
        LabSessionLogFactory(
            computing_equipment=comp,
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/lab-efficiency?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_response_items_have_required_fields(self, auth_client, db):
        comp = ComputingEquipmentFactory()
        LabSessionLogFactory(
            computing_equipment=comp,
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/lab-efficiency?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        data = resp.json()["data"]
        if data:
            item = data[0]
            assert "name" in item
            assert "efficiency" in item
            assert "duration" in item
            assert "booking" in item

    def test_null_computer_name_is_returned_as_na(self, auth_client, db):
        LabSessionLogFactory(
            computing_equipment=None,
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/lab-efficiency?from_date_time={FROM_DT}&to_date_time={TO_DT}")

        assert resp.status_code == 200
        assert resp.json()["data"][0]["computer_name"] == "N/A"


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/project-usage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProjectUsage:
    def test_missing_dates_returns_400(self, auth_client):
        resp = auth_client.get(f"{BASE}/project-usage")
        assert resp.status_code == 400

    def test_returns_200_with_date_range(self, auth_client, db):
        proj = LabProjectFactory()
        booking = BenchBookingFactory(project=proj)
        LabSessionLogFactory(
            booking_code=booking.booking_code,
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/project-usage?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        assert resp.status_code == 200

    def test_response_has_project_name_and_usage(self, auth_client, db):
        proj = LabProjectFactory()
        booking = BenchBookingFactory(project=proj)
        LabSessionLogFactory(
            booking_code=booking.booking_code,
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/project-usage?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        data = resp.json()["data"]
        if data:
            assert "project_name" in data[0]
            assert "usage" in data[0]


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/user-lab-usage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserLabUsage:
    def test_missing_dates_returns_400(self, auth_client):
        resp = auth_client.get(f"{BASE}/user-lab-usage")
        assert resp.status_code == 400

    def test_returns_200(self, auth_client, db):
        LabSessionLogFactory(
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/user-lab-usage?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        assert resp.status_code == 200

    def test_response_has_user_and_usage(self, auth_client, db):
        LabSessionLogFactory(
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/user-lab-usage?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        data = resp.json()["data"]
        if data:
            assert "remote_user" in data[0]
            assert "usage" in data[0]


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/user-booking-efficiency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserBookingEfficiency:
    def test_missing_dates_returns_400(self, auth_client):
        resp = auth_client.get(f"{BASE}/user-booking-efficiency")
        assert resp.status_code == 400

    def test_returns_200(self, auth_client, db):
        LabSessionLogFactory(
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/user-booking-efficiency?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        assert resp.status_code == 200

    def test_response_has_efficiency(self, auth_client, db):
        booking = BenchBookingFactory(
            starts_at=NOW - timedelta(hours=4),
            ends_at=NOW - timedelta(hours=1),
        )
        LabSessionLogFactory(
            booking_code=booking.booking_code,
            login_time=NOW - timedelta(hours=3),
            logout_time=NOW - timedelta(hours=1),
        )
        resp = auth_client.get(f"{BASE}/user-booking-efficiency?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        data = resp.json()["data"]
        if data:
            assert "remote_user" in data[0]
            assert "efficiency" in data[0]


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/lab-usage-by-timeframe
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLabUsageByTimeframe:
    def test_missing_dates_returns_400(self, auth_client):
        resp = auth_client.get(f"{BASE}/lab-usage-by-timeframe")
        assert resp.status_code == 400

    def test_returns_200_with_12_timeslots(self, auth_client, db):
        resp = auth_client.get(f"{BASE}/lab-usage-by-timeframe?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 12

    def test_timeslot_shape(self, auth_client, db):
        resp = auth_client.get(f"{BASE}/lab-usage-by-timeframe?from_date_time={FROM_DT}&to_date_time={TO_DT}")
        item = resp.json()["data"][0]
        assert "timeslot" in item
        assert "usage" in item
        assert item["timeslot"] == "00h-02h"


# ---------------------------------------------------------------------------
# GET+POST /api/labs/analytics/storage-quota
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStorageQuota:
    def test_missing_log_date_returns_400(self, auth_client):
        resp = auth_client.get(f"{BASE}/storage-quota")
        assert resp.status_code == 400

    def test_get_returns_200(self, auth_client, db):
        comp = ComputingEquipmentFactory()
        StorageQuotaMeasurementFactory(computer_identifier=comp.sku, used_gibibytes=90, quota_gibibytes=100)
        resp = auth_client.get(f"{BASE}/storage-quota?log_date={NOW.isoformat()}")
        assert resp.status_code == 200

    def test_get_response_shape(self, auth_client, db):
        comp = ComputingEquipmentFactory()
        StorageQuotaMeasurementFactory(computer_identifier=comp.sku, used_gibibytes=90, quota_gibibytes=100)
        resp = auth_client.get(f"{BASE}/storage-quota?log_date={NOW.isoformat()}")
        data = resp.json()["data"]
        if data:
            assert "username" in data[0]
            assert "used" in data[0]
            assert "quota" in data[0]

    def test_post_requires_valid_sku(self, auth_client, db):
        payload = {
            "username": "user1",
            "used": 50.0,
            "quota": 100.0,
            "source": "collector",
            "user_displayname": "User One",
            "computer_sku": "INVALID-SKU",
        }
        resp = auth_client.post(f"{BASE}/storage-quota", data=payload)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET+POST /api/labs/analytics/lab-visits
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVisitCount:
    def test_get_returns_200(self, auth_client):
        resp = auth_client.get(f"{BASE}/lab-visits")
        assert resp.status_code == 200

    def test_get_count_and_trend(self, auth_client, db):
        resp = auth_client.get(f"{BASE}/lab-visits")
        body = resp.json()["data"]
        assert "count" in body
        assert "trend" in body

    def test_get_with_unit_returns_list(self, auth_client, db):
        VisitorVolumeObservationFactory(distinct_visitor_count=5)
        resp = auth_client.get(f"{BASE}/lab-visits?unit=day")
        data = resp.json()["data"]
        assert isinstance(data, list)

    def test_post_creates_visit_log(self, auth_client, db):
        resp = auth_client.post(f"{BASE}/lab-visits", data={})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/booking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBookingCount:
    def test_returns_200(self, auth_client):
        resp = auth_client.get(f"{BASE}/booking")
        assert resp.status_code == 200

    def test_response_has_count_and_trend(self, auth_client, db):
        body = auth_client.get(f"{BASE}/booking").json()["data"]
        assert "count" in body
        assert "trend" in body

    def test_unit_param_returns_list(self, auth_client, db):
        BookingVolumeObservationFactory()
        resp = auth_client.get(f"{BASE}/booking?unit=week")
        assert isinstance(resp.json()["data"], list)


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/lab-count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLabCount:
    def test_returns_200(self, auth_client):
        resp = auth_client.get(f"{BASE}/lab-count")
        assert resp.status_code == 200

    def test_count_reflects_active_labs(self, auth_client, db):
        BenchFactory()
        resp = auth_client.get(f"{BASE}/lab-count")
        data = resp.json()["data"]
        assert data["count"] >= 1


# ---------------------------------------------------------------------------
# GET /api/labs/analytics/user-count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserCount:
    def test_returns_200(self, auth_client):
        resp = auth_client.get(f"{BASE}/user-count")
        assert resp.status_code == 200

    def test_count_reflects_active_users(self, auth_client, db):
        UserFactory(is_active=True)
        resp = auth_client.get(f"{BASE}/user-count")
        data = resp.json()["data"]
        assert data["count"] >= 1
