from decimal import Decimal
from types import SimpleNamespace

from core.labs.features.equipment.api.serializers import (
    EquipmentCreateSerializer,
    EquipmentSerializer,
    EquipmentStatusRecordSerializer,
)
from core.labs.models import EquipmentStatus


def test_equipment_serializer_canonical_fields():
    fields = EquipmentSerializer.Meta.fields
    assert "status" in fields
    assert "acquisition_price" in fields
    assert "created_at" in fields
    assert "updated_at" in fields
    assert "created" not in fields
    assert "modified" not in fields
    assert "deleted_at" not in fields
    assert "group" in fields
    assert "department" in fields
    assert "current_status" not in fields
    assert "acquisition" not in fields

    equipment = SimpleNamespace(
        current_status=EquipmentStatus.AVAILABLE,
        acquisition_price=Decimal("499.00"),
        acquisition_currency="USD",
    )
    assert EquipmentSerializer().get_status(equipment) == {"value": "available", "label": "Available"}
    assert EquipmentSerializer().get_acquisition_price(equipment) == {
        "amount": "499.00",
        "currency": "USD",
    }


def test_equipment_serializer_renders_group_as_named_reference_or_null():
    serializer = EquipmentSerializer()

    assert serializer.fields["group"].to_representation(SimpleNamespace(id=12, name="Optics")) == {
        "id": 12,
        "name": "Optics",
    }
    assert serializer.fields["group"].to_representation(None) == {}


def test_equipment_create_serializer_accepts_relation_ids():
    serializer = EquipmentCreateSerializer(
        data={
            "sku": "EQ-CANONICAL-01",
            "name": "Multimeter",
            "kind_id": 1,
            "type_id": 2,
            "manufacturer_id": 3,
            "product_model_id": 4,
            "owner_id": 5,
            "department_id": 6,
            "group_id": 7,
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["kind"] == 1
    assert serializer.validated_data["manufacturer"] == 3
    assert serializer.validated_data["department"] == 6
    assert serializer.validated_data["group"] == 7


def test_equipment_status_record_serializer_canonical_fields():
    fields = EquipmentStatusRecordSerializer.Meta.fields
    assert "status" in fields
    assert "created_at" in fields
    assert "created" not in fields

    record = SimpleNamespace(status=EquipmentStatus.MAINTENANCE)
    assert EquipmentStatusRecordSerializer().get_status(record) == {
        "value": "maintenance",
        "label": "Maintenance",
    }


def test_computing_create_accepts_manual_fields_and_excludes_agent_reported_ones():
    from django.urls import resolve

    urlconf = "core.labs.features.equipment.api.urls"
    create_serializer_class = resolve("/equipment/computing", urlconf=urlconf).func.view_class.create_serializer_class

    # Owner decision: hostname (RDP host) and MAC are entered manually at registration;
    # ip_address, os_name and system_info are reported by the monitoring agent.
    create_serializer = create_serializer_class()
    assert "hostname" in create_serializer.fields
    assert "mac_address" in create_serializer.fields
    for agent_owned in ("ip_address", "os_name", "system_info"):
        assert agent_owned not in create_serializer.fields
