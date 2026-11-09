import uuid
from types import SimpleNamespace

from core.labs.features.benches.api.serializers import (
    BenchCreateSerializer,
    BenchGroupSerializer,
    BenchPlacementSerializer,
    BenchSerializer,
    BenchSetupEquipmentSerializer,
    BenchTypeSerializer,
)


def test_bench_serializer_contains_standard_contract_fields():
    fields = BenchSerializer.Meta.fields
    assert "status" in fields
    assert "created_at" in fields
    assert "updated_at" in fields
    assert "created" not in fields
    assert "modified" not in fields
    assert "deleted_at" not in fields
    assert "current_status" not in fields
    assert "lifecycle_status" not in fields
    assert "equipment_count" in fields
    assert "equipment_url" in fields

    bench = SimpleNamespace(lifecycle_status="active", equipment_count=0)
    ref = BenchSerializer().get_status(bench)
    assert ref == {"value": "active", "label": "Active"}


def test_bench_setup_equipment_serializer_remains_available_for_subresource_and_is_monitored():
    eq_id = 42
    eq_uid = uuid.uuid4()
    eq = SimpleNamespace(id=eq_id, uid=eq_uid, sku="EQ-100", name="Oscilloscope", kind_id="measuring")
    assignment = SimpleNamespace(
        id=1,
        equipment=eq,
        role="main",
        position=0,
        monitor=True,
        assigned_at="2026-10-17T10:00:00Z",
    )
    serializer = BenchSetupEquipmentSerializer(assignment)
    data = serializer.data
    assert data["equipment"]["id"] == eq_id
    assert str(data["equipment"]["uid"]) == str(eq_uid)
    assert data["equipment"]["name"] == "Oscilloscope"
    assert data["is_monitored"] is True
    # Verify legacy flattened fields are eliminated
    assert "equipment_id" not in data
    assert "monitor" not in data


def test_bench_create_serializer_accepts_relation_id_keys():
    serializer = BenchCreateSerializer(
        data={
            "sku": "BN-TEST-01",
            "name": "Bench Test 01",
            "group_id": 1,
            "owner_id": 2,
            "type_id": 3,
            "bench_group_id": 4,
            "setup_location_id": 5,
            "station_slot_id": 6,
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["group_id"] == 1
    assert serializer.validated_data["owner_id"] == 2
    assert serializer.validated_data["type_id"] == 3
    assert serializer.validated_data["bench_group_id"] == 4
    assert serializer.validated_data["setup_location_id"] == 5
    assert serializer.validated_data["station_slot_id"] == 6


def test_bench_placement_serializer_accepts_relation_id_keys():
    serializer = BenchPlacementSerializer(data={"setup_location_id": 1, "station_slot_id": 2})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["setup_location_id"] == 1
    assert serializer.validated_data["station_slot_id"] == 2


def test_bench_reference_serializers_standard_booleans_and_timestamps():
    for serializer_cls in (BenchGroupSerializer, BenchTypeSerializer):
        fields = serializer_cls.Meta.fields
        assert "is_active" in fields
        assert "active" not in fields
        assert "created_at" in fields
        assert "updated_at" in fields
        assert "created" not in fields
        assert "modified" not in fields
