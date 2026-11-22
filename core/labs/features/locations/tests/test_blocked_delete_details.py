"""Tests for structured blocked-delete conflict details on rooms, stations, benches, and licenses."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.public import PlaceEquipmentInput, place_equipment
from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import (
    Bench,
    BenchBooking,
    Equipment,
    EquipmentAssignment,
    EquipmentCategory,
    EquipmentKind,
    LicenseAssignment,
    Room,
    Station,
)
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)

User = get_user_model()
ROOT = "/api/labs/"


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _details_by_group(details: list[dict]) -> tuple[dict[str, int], dict[str, list[str]]]:
    totals: dict[str, int] = {}
    items: dict[str, list[str]] = {}
    for entry in details:
        field = entry.get("field") or ""
        message = str(entry.get("message") or "")
        if field.endswith("_total"):
            totals[field[: -len("_total")]] = int(message)
        elif "[" in field:
            group = field.split("[", 1)[0]
            items.setdefault(group, []).append(message)
    return totals, items


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="bd-coord"), "coord")


@pytest.fixture
def equipment_kind(db):
    category = EquipmentCategory.objects.create(key="bd-samples", name="BD Samples", definition="BD Samples")
    return EquipmentKind.objects.create(category=category, name="BD Sample Kind")


@pytest.mark.django_db
def test_room_delete_returns_both_station_and_equipment_blockers(coordinator, equipment_kind):
    room = Room.objects.create(sku="BD-RM-01", name="Blocked Room")
    for idx in range(6):
        Station.objects.create(sku=f"BD-ST-0{idx}", name=f"Station {idx}", room=room)
    unit = Equipment.objects.create(kind=equipment_kind, sku="BD-EQ-RM", name="Room Scope")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, room_id=room.pk), actor=coordinator)

    response = _client(coordinator).delete(ROOT + f"rooms/{room.pk}")
    assert response.status_code == 409, response.data
    assert response.data["error"]["code"] == "room_conflict"
    totals, items = _details_by_group(response.data["error"]["details"])
    assert totals == {"stations": 6, "equipment": 1}
    assert len(items["stations"]) == 5
    assert items["stations"][0] == "BD-ST-00 — Station 0"
    assert items["equipment"] == ["BD-EQ-RM — Room Scope"]


@pytest.mark.django_db
def test_station_delete_returns_both_bench_and_equipment_blockers(coordinator, equipment_kind):
    room = Room.objects.create(sku="BD-RM-02", name="Station Room")
    station = Station.objects.create(sku="BD-ST-10", name="Blocked Station", room=room)
    Bench.objects.create(sku="BD-BN-01", name="Alpha Bench", setup_location=station)
    unit = Equipment.objects.create(kind=equipment_kind, sku="BD-EQ-ST", name="Station Meter")
    place_equipment(PlaceEquipmentInput(equipment_id=unit.pk, station_id=station.pk), actor=coordinator)

    response = _client(coordinator).delete(ROOT + f"stations/{station.pk}")
    assert response.status_code == 409, response.data
    assert response.data["error"]["code"] == "location_conflict"
    totals, items = _details_by_group(response.data["error"]["details"])
    assert totals == {"benches": 1, "equipment": 1}
    assert items["benches"] == ["BD-BN-01 — Alpha Bench"]
    assert items["equipment"] == ["BD-EQ-ST — Station Meter"]


@pytest.mark.django_db
def test_bench_delete_returns_both_equipment_and_booking_blockers(coordinator, equipment_kind):
    bench = Bench.objects.create(sku="BD-BN-20", name="Blocked Bench")
    unit = Equipment.objects.create(kind=equipment_kind, sku="BD-EQ-BN", name="Bench Oscilloscope")
    now = timezone.now()
    EquipmentAssignment.objects.create(equipment=unit, bench=bench, assigned_at=now)
    BenchBooking.objects.create(
        bench=bench,
        booking_code="BD-BB-01",
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=3),
    )

    response = _client(coordinator).delete(ROOT + f"benches/{bench.pk}")
    assert response.status_code == 409, response.data
    assert response.data["error"]["code"] == "bench_conflict"
    totals, items = _details_by_group(response.data["error"]["details"])
    assert totals == {"equipment": 1, "bookings": 1}
    assert items["equipment"] == ["BD-EQ-BN — Bench Oscilloscope"]
    assert items["bookings"] == ["BD-BB-01"]


@pytest.mark.django_db
def test_license_delete_returns_assigned_equipment_blockers(coordinator, equipment_kind):
    unit = Equipment.objects.create(kind=equipment_kind, sku="BD-EQ-LIC", name="Licensed Host")
    lic = License.objects.create(
        name="BD License",
        sku="BD-LIC-01",
        category=LicenseCategory.objects.create(name="BD Lic Cat"),
        product=LicenseProduct.objects.create(name="BD Lic Prod"),
        vendor=LicenseVendor.objects.create(name="BD Lic Vendor"),
        type=LicenseType.objects.create(name="BD Lic Type"),
        identifier="BD-LIC-ID",
        seats=1,
    )
    LicenseAssignment.objects.create(license=lic, equipment=unit)

    response = _client(coordinator).delete(ROOT + f"licenses/{lic.pk}")
    assert response.status_code == 409, response.data
    assert response.data["error"]["code"] == "license_conflict"
    totals, items = _details_by_group(response.data["error"]["details"])
    assert totals == {"equipment": 1}
    assert items["equipment"] == ["BD-EQ-LIC — Licensed Host"]
