from types import SimpleNamespace

from core.labs.features.locations.rooms.api.serializers import (
    RoomCreateSerializer,
    RoomSerializer,
)
from core.labs.features.locations.stations.api.serializers import (
    StationCreateSerializer,
    StationPlacementSerializer,
    StationSerializer,
)
from core.labs.features.locations.stations.api.views import StationListCreateAPIView
from core.labs.models import RoomStatus, StationStatus


def test_room_serializer_contract():
    fields = RoomSerializer.Meta.fields
    assert "status" in fields
    assert "operational_status" not in fields
    assert "created_at" in fields
    assert "updated_at" in fields
    assert "created" not in fields
    assert "modified" not in fields
    assert "deleted_at" not in fields
    assert "current_status" not in fields

    room = SimpleNamespace(current_status=RoomStatus.AVAILABLE)
    status_ref = RoomSerializer().get_status(room)
    assert status_ref == {"value": "available", "label": "Available"}


def test_room_create_serializer_accepts_relation_ids():
    serializer = RoomCreateSerializer(
        data={
            "sku": "RM-TEST-01",
            "name": "Room 01",
            "group_id": 1,
            "owner_id": 2,
            "country_id": 3,
            "city_id": 4,
            "building_id": 5,
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["group_id"] == 1
    assert serializer.validated_data["owner_id"] == 2
    assert serializer.validated_data["country_id"] == 3


def test_station_serializer_contract_and_coordinates():
    fields = StationSerializer.Meta.fields
    assert "status" in fields
    assert "operational_status" not in fields
    assert "position" in fields
    assert "created_at" in fields
    assert "updated_at" in fields
    assert "created" not in fields
    assert "modified" not in fields
    assert "deleted_at" not in fields
    assert "current_status" not in fields

    station = SimpleNamespace(
        current_status=StationStatus.AVAILABLE,
        position=[12.5, 34.0, 56.5],
    )
    assert StationSerializer().get_status(station) == {"value": "available", "label": "Available"}
    assert StationSerializer().get_position(station) == {"x": 12.5, "y": 34.0, "z": 56.5}


def test_station_placement_serializer_accepts_dict_and_list_position():
    # Dict coordinates
    s1 = StationPlacementSerializer(data={"room_id": 1, "position": {"x": 10.0, "y": 20.0, "z": 30.0}})
    assert s1.is_valid(), s1.errors
    assert s1.validated_data["position"] == [10.0, 20.0, 30.0]

    # List coordinates
    s2 = StationPlacementSerializer(data={"room_id": 1, "position": [10.0, 20.0, 30.0]})
    assert s2.is_valid(), s2.errors
    assert s2.validated_data["position"] == [10.0, 20.0, 30.0]


def test_station_placement_rejects_malformed_coordinates_as_validation_errors():
    for position in (
        {"x": "not-a-number", "y": 0, "z": 0},
        {"x": 1, "y": 2},
        {"x": 1, "y": 2, "z": 3, "extra": 4},
        [True, 0, 0],
        [float("inf"), 0, 0],
        [1, 2],
    ):
        serializer = StationPlacementSerializer(data={"position": position})
        assert not serializer.is_valid()
        assert "position" in serializer.errors


def test_station_create_serializer_accepts_relation_ids():
    serializer = StationCreateSerializer(
        data={
            "sku": "ST-TEST-01",
            "name": "Station 01",
            "group_id": 1,
            "owner_id": 2,
            "type_id": 3,
            "room_id": 4,
            "slot_id": 5,
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["group_id"] == 1
    assert serializer.validated_data["room_id"] == 4


def test_station_list_passes_declared_room_and_type_filters():
    from unittest.mock import patch

    request = type("Request", (), {"user": object()})()
    view = StationListCreateAPIView()
    filters = {"room_id": [4], "type_id": [8], "q": "bench"}
    with patch.object(view, "validate_query", return_value=(filters, None)), patch(
        "core.labs.features.locations.stations.api.views.selectors.list_stations",
        return_value=object(),
    ) as list_stations, patch(
        "core.labs.features.locations.stations.api.views.STATION_FILTERS.apply", return_value=object(),
    ) as apply_filters, patch.object(view, "_execute", side_effect=lambda callback: callback()):
        response = view.handle_get(request)

    assert response is not None
    list_stations.assert_called_once_with()
    apply_filters.assert_called_once_with(list_stations.return_value, filters)
