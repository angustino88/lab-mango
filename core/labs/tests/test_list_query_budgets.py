"""Regression tests for N+1 queries on resource list endpoints.

Each list must issue the same number of queries regardless of page size; the
annotated values must equal what the per-row model properties used to compute.
"""

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from core.labs.features.dashboard.tests.api.test_views import make_license
from core.labs.models import ResourceServiceRecord, Room, Station
from core.labs.models.resource.license.assignment import LicenseAssignment
from core.labs.models.resource.location.station_slot import StationSlot
from tests.factories import ComputingEquipmentFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    client = APIClient()
    client.force_authenticate(UserFactory(username="list-budget-admin", is_staff=True, is_superuser=True))
    return client


def _room():
    return Room.objects.create(sku=f"RM-{uuid.uuid4().hex[:8]}", name="Budget room")


def _station():
    station = Station.objects.create(sku=f"ST-{uuid.uuid4().hex[:8]}", name="Budget station", room=_room())
    StationSlot.objects.create(station=station, position_index=1, slot_code="A1")
    return station


def _license():
    license_ = make_license(seats=5)
    LicenseAssignment.objects.create(license=license_, equipment=ComputingEquipmentFactory())
    return license_


def _calibrated_equipment():
    equipment = ComputingEquipmentFactory(calibration_required=True)
    ResourceServiceRecord.for_new_resource(
        equipment,
        kind=ResourceServiceRecord.Kind.CALIBRATION,
        performed_at=timezone.now() - timedelta(days=30),
        next_due_at=timezone.now() + timedelta(days=335),
    ).save()
    return equipment


def _query_count(client, url):
    with CaptureQueriesContext(connection) as context:
        response = client.get(url, {"page_size": 50})
    assert response.status_code == 200, response.content
    return len(context.captured_queries)


@pytest.mark.parametrize(
    ("url", "seed"),
    [
        ("/api/labs/licenses", _license),
        ("/api/labs/stations", _station),
        ("/api/labs/equipment", _calibrated_equipment),
    ],
)
def test_list_query_count_does_not_grow_with_rows(admin_client, url, seed):
    for _ in range(2):
        seed()
    _query_count(admin_client, url)  # warm per-process caches (ContentType, roles)
    small = _query_count(admin_client, url)
    for _ in range(6):
        seed()
    large = _query_count(admin_client, url)

    assert large == small, f"{url}: {small} queries for 2 rows but {large} for 8 rows"


def test_license_seats_in_use_counts_only_active_assignments(admin_client):
    license_ = _license()
    LicenseAssignment.objects.create(
        license=license_,
        equipment=ComputingEquipmentFactory(),
        assigned_at=timezone.now() - timedelta(days=2),
        unassigned_at=timezone.now() - timedelta(days=1),
    )

    rows = admin_client.get("/api/labs/licenses").json()["data"]

    row = next(item for item in rows if item["id"] == license_.pk)
    assert row["seats_in_use"] == 1 == license_.seats_in_use


def test_station_slot_count_matches_slots(admin_client):
    station = _station()
    StationSlot.objects.create(station=station, position_index=2, slot_code="A2", status="out_of_service")

    rows = admin_client.get("/api/labs/stations").json()["data"]

    assert next(item for item in rows if item["id"] == station.pk)["slot_count"] == 2


def test_equipment_calibration_fields_match_model_properties(admin_client):
    equipment = _calibrated_equipment()
    uncalibrated = ComputingEquipmentFactory(calibration_required=True)

    rows = {item["id"]: item for item in admin_client.get("/api/labs/equipment").json()["data"]}

    record = equipment.latest_service_record("calibration")
    calibrated_row = rows[equipment.pk]
    assert calibrated_row["last_calibrated_at"] is not None
    assert calibrated_row["next_calibration_due_at"] is not None
    assert calibrated_row["calibration_overdue"] is False
    assert parse_datetime(calibrated_row["last_calibrated_at"]) == record.performed_at
    assert parse_datetime(calibrated_row["next_calibration_due_at"]) == record.next_due_at
    assert rows[uncalibrated.pk]["last_calibrated_at"] is None
    assert rows[uncalibrated.pk]["calibration_overdue"] is True  # required but never calibrated
