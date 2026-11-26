"""Room mapping carries what the DCIM floor plan draws: room size, slot kinds, layout, capacity, rack, conditions."""

from decimal import Decimal

import pytest

from core.labs.features.equipment.public import PlaceEquipmentInput, place_equipment
from core.labs.features.resource_mappings.queries import get_resource_mapping
from core.labs.models import Room, Station
from core.labs.models.resource.location.room_slot import RoomSlot
from tests.factories import ComputingEquipmentFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_room_mapping_has_floor_plan_capacity_and_rack_rows():
    actor = UserFactory.create(is_superuser=True)
    room = Room.objects.create(sku="DCIM-R", name="DCIM room", length_m=Decimal("12.5"), width_m=Decimal("8"))
    aisle = RoomSlot.objects.create(room=room, row_index=0, col_index=0, slot_code="R1C1", slot_type="aisle")
    station = Station.objects.create(
        sku="DCIM-S", name="Rack", room=room, rack_units=42, power_capacity_w=5000, width_mm=600, depth_mm=1000
    )
    equipment = ComputingEquipmentFactory.create(power_draw_w=450)
    place_equipment(
        PlaceEquipmentInput(
            equipment_id=equipment.pk, station_id=station.pk, rack_unit=5, rack_unit_height=2, rack_face="front"
        ),
        actor=actor,
    )

    data = get_resource_mapping(resource_type="rooms", resource_id=room.pk)["data"]

    [room_row] = data["rooms"]
    assert (room_row["length_m"], room_row["width_m"], room_row["conditions"]) == (Decimal("12.5"), Decimal("8"), None)
    assert [(slot["id"], slot["slot_type"], slot["status"]) for slot in data["room_slots"]] == [
        (aisle.pk, "aisle", "usable")
    ]
    [station_row] = data["stations"]
    assert station_row["layout"]["width_mm"] == 600
    assert station_row["capacity"] | {} == {
        "bench_capacity": None,
        "rack_units": 42,
        "power_capacity_w": 5000,
        "power_reserved_w": 0,
        "max_load_kg": None,
        "network_port_capacity": None,
        "power_installed_w": 450.0,
        "load_installed_kg": 0.0,
        "installed_units": 1,
        "rack_units_used": 2,
    }
    assert [(item["equipment_id"], item["rack_unit"], item["rack_unit_height"]) for item in station_row["rack"]] == [
        (equipment.pk, 5, 2)
    ]
    assert station_row["conditions"] is None
