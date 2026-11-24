"""Unit tests for support_desk resource adapters against canonical Labs models."""

import pytest
from django.utils import timezone

from core.labs.models import (
    Bench,
    Building,
    City,
    Country,
    Equipment,
    EquipmentAssignment,
    EquipmentCategory,
    EquipmentKind,
    License,
    Room,
    Station,
)
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from core.support_desk.features.tickets.application.adapters import (
    BenchAdapter,
    EquipmentAdapter,
    LicenseAdapter,
    RoomAdapter,
    StationAdapter,
)
from core.users.tests.factories import UserFactory


@pytest.mark.django_db
def test_room_station_bench_equipment_license_adapters():
    user = UserFactory()
    country = Country.objects.create(name="Germany", code="DE")
    city = City.objects.create(name="Munich", country=country)
    building = Building.objects.create(name="Bldg A", city=city)
    room = Room.objects.create(
        name="Lab 101",
        sku="RM-101",
        country=country,
        city=city,
        building=building,
    )
    station = Station.objects.create(name="Station Alpha", sku="ST-01", room=room)
    bench = Bench.objects.create(name="Bench One", sku="BN-01", setup_location=station)

    category, _ = EquipmentCategory.objects.get_or_create(
        key="instrument",
        defaults={"name": "Instrument", "definition": "Measurement instruments"},
    )
    kind = EquipmentKind.objects.create(name="Scope", category=category)
    equipment = Equipment.objects.create(name="Oscilloscope X", sku="EQ-001", kind=kind)
    EquipmentAssignment.all_placements.create(
        equipment=equipment,
        bench=bench,
        assigned_at=timezone.now(),
    )

    vendor = LicenseVendor.objects.create(name="Vector")
    product = LicenseProduct.objects.create(name="CANoe", vendor=vendor)
    lic_type = LicenseType.objects.create(name="Floating")
    lic_category = LicenseCategory.objects.create(name="Simulation")
    lic = License.objects.create(
        name="CANoe Pro",
        sku="LIC-001",
        vendor=vendor,
        product=product,
        type=lic_type,
        category=lic_category,
    )

    room_ref = RoomAdapter().get_reference(room.pk)
    assert room_ref is not None
    assert room_ref.code == "RM-101"
    assert room_ref.parent_context == "Location: Bldg A, Munich, Germany"
    assert room_ref.is_active is True
    assert len(RoomAdapter().search("RM-101", user)) == 1

    station_ref = StationAdapter().get_reference(station.pk)
    assert station_ref is not None
    assert station_ref.code == "ST-01"
    assert station_ref.parent_context == "Room: Lab 101"
    assert len(StationAdapter().search("Alpha", user)) == 1

    bench_ref = BenchAdapter().get_reference(bench.pk)
    assert bench_ref is not None
    assert bench_ref.code == "BN-01"
    assert bench_ref.parent_context == "Station: Station Alpha, Room: Lab 101"
    assert len(BenchAdapter().search("BN-01", user)) == 1

    eq_ref = EquipmentAdapter().get_reference(equipment.pk)
    assert eq_ref is not None
    assert eq_ref.code == "EQ-001"
    assert eq_ref.parent_context == "Bench: Bench One"
    assert len(EquipmentAdapter().search("EQ-001", user)) == 1

    lic_ref = LicenseAdapter().get_reference(lic.pk)
    assert lic_ref is not None
    assert lic_ref.name == "CANoe Pro"
    assert lic_ref.code == "LIC-001"
    assert lic_ref.parent_context == "Vendor: Vector"
    assert lic_ref.is_active is True
    assert len(LicenseAdapter().search("CANoe", user)) == 1
    assert len(LicenseAdapter().search("LIC-001", user)) == 1
