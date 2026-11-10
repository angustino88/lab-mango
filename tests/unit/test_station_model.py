import pytest
from django.core.exceptions import ValidationError

from core.labs.models.resource.location.physical_location import PhysicalLocationNode
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.room_slot import RoomSlot
from core.labs.models.resource.location.station import Station


def test_station_clean_allows_unassigned_station():
    Station(sku="ST-01").clean()


def test_station_clean_allows_room_without_slot():
    station = Station(sku="ST-01", room=Room(pk=1, sku="RM-01"))

    station.clean()


def test_station_clean_allows_slot_in_same_room():
    room = Room(pk=1, sku="RM-01")
    station = Station(sku="ST-01", room=room, slot=RoomSlot(pk=1, room=room))

    station.clean()


def test_station_clean_rejects_slot_without_room():
    station = Station(sku="ST-01", slot=RoomSlot(pk=1, room_id=1))

    with pytest.raises(ValidationError) as exc_info:
        station.clean()

    assert exc_info.value.message_dict == {"slot": ["A station must have a room before assigning a slot."]}


def test_station_clean_rejects_slot_in_different_room():
    station = Station(
        sku="ST-01",
        room=Room(pk=1, sku="RM-01"),
        slot=RoomSlot(pk=1, room_id=2),
    )

    with pytest.raises(ValidationError) as exc_info:
        station.clean()

    assert exc_info.value.message_dict == {"slot": ["The assigned slot must belong to the station's room."]}


def test_station_clean_preserves_parent_validation(monkeypatch):
    def reject_location(self):
        raise ValidationError("Invalid location hierarchy.")

    monkeypatch.setattr(PhysicalLocationNode, "clean", reject_location)

    with pytest.raises(ValidationError, match="Invalid location hierarchy"):
        Station(sku="ST-01").clean()


@pytest.mark.parametrize(
    ("label", "sku", "name", "expected"),
    [
        ("Station 01", "ST-01", "Station name", "Station 01"),
        (None, "ST-01", "Station name", "ST-01"),
        ("", "", "Station name", "Station name"),
    ],
)
def test_station_location_segment_preserves_fallback(label, sku, name, expected):
    station = Station(label=label, sku=sku, name=name)

    assert station.get_location_segment() == expected


def test_station_location_parent_is_room():
    room = Room(pk=1, sku="RM-01")

    assert Station(sku="ST-01", room=room).get_location_parent() is room
    assert Station(sku="ST-02").get_location_parent() is None
