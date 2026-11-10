from decimal import Decimal

import pytest
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import UniqueConstraint

from core.common.models import TimestampedSoftDeleteManager
from core.labs.models.resource.location.physical_location import PhysicalLocationNode
from core.labs.models.resource.location.room import Building, City, Country, Room
from core.labs.models.resource.location.room_observation import RoomObservation


@pytest.mark.parametrize(
    ("length", "width", "expected"),
    [(Decimal("2.125"), Decimal("4.000"), Decimal("8.500000")), (None, Decimal("4"), None)],
)
def test_room_area_uses_explicit_units(length, width, expected):
    assert Room(length_m=length, width_m=width).area_m2 == expected


def test_room_capacity_is_derived():
    room = Room(sku="RM-01", layout_rows=2, layout_columns=3)
    room.clean()
    assert room.slot_capacity == 6
    room.layout_columns = 4
    assert room.slot_capacity == 8


def test_room_without_layout():
    room = Room(sku="RM-01")
    room.clean()
    assert room.slot_capacity is None
    assert room.area_m2 is None
    assert room.get_location_parent() is None


@pytest.mark.parametrize(("rows", "columns", "missing"), [(2, None, "layout_columns"), (None, 3, "layout_rows")])
def test_room_rejects_partial_layout(rows, columns, missing):
    with pytest.raises(ValidationError) as exc_info:
        Room(sku="RM-01", layout_rows=rows, layout_columns=columns).clean()
    assert missing in exc_info.value.message_dict


@pytest.mark.parametrize(
    ("field", "value"), [("length_m", 0), ("width_m", -1), ("layout_rows", 0), ("layout_columns", 0)]
)
def test_room_fields_reject_nonpositive_dimensions(field, value):
    room = Room()
    with pytest.raises(ValidationError):
        room._meta.get_field(field).clean(value, room)


def test_room_preserves_parent_validation(monkeypatch):
    def reject_location(self):
        raise ValidationError("Invalid location hierarchy.")

    monkeypatch.setattr(PhysicalLocationNode, "clean", reject_location)
    with pytest.raises(ValidationError, match="Invalid location hierarchy"):
        Room().clean()


def test_room_geographic_location():
    room = Room(
        sku="RM-01",
        label="Lab A",
        floor="3",
        country=Country(pk=1, code="US", name="United States"),
        city=City(pk=1, name="New York"),
        building=Building(pk=1, name="HQ"),
    )
    assert room.get_location_path() == "US-New York-HQ-3F-Lab A"
    assert str(room) == room.get_location_path()


def test_room_inherits_resource_contract():
    room = Room(sku="RM-01")
    active_sku_constraints = [
        c
        for c in Room._meta.constraints
        if isinstance(c, UniqueConstraint) and c.fields == ("sku",) and c.name == "labs_room_active_sku_uniq"
    ]
    assert len(active_sku_constraints) == 1
    assert room.deleted_at is None
    assert isinstance(Room.objects, TimestampedSoftDeleteManager)
    for field in ("uid", "owner", "image", "remark"):
        assert room._meta.get_field(field)
    for field in ("primary_owner", "is_delete", "temperature", "humidity", "power_usage", "setup_capacity"):
        with pytest.raises(FieldDoesNotExist):
            room._meta.get_field(field)


def test_observation_requires_measurement():
    with pytest.raises(ValidationError, match="at least one measurement"):
        RoomObservation().clean()


@pytest.mark.parametrize("values", [{"temperature_c": -20}, {"humidity_percent": 0}, {"power_usage_w": 0}])
def test_observation_accepts_independent_and_zero_measurements(values):
    RoomObservation(**values).clean()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature_c", Decimal("-273.16")),
        ("humidity_percent", -1),
        ("humidity_percent", 101),
        ("power_usage_w", -1),
    ],
)
def test_observation_rejects_invalid_measurements(field, value):
    observation = RoomObservation()
    with pytest.raises(ValidationError):
        observation._meta.get_field(field).clean(value, observation)
