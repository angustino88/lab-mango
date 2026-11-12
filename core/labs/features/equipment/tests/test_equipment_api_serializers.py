from decimal import Decimal
from types import SimpleNamespace

from core.labs.features.equipment.api.serializers import (
    EquipmentCreateSerializer,
    EquipmentSerializer,
)


def test_equipment_serializer_canonical_fields():
    fields = EquipmentSerializer.Meta.fields
    assert {"display_status", "lifecycle_state", "condition", "placement"} <= set(fields)
    assert "status" not in fields
    assert "acquisition_price" in fields
    assert "created_at" in fields
    assert "updated_at" in fields
    assert "created" not in fields
    assert "modified" not in fields
    assert "deleted_at" not in fields
    assert "team" in fields
    assert "department" in fields
    assert "current_status" not in fields
    assert "acquisition" not in fields

    equipment = SimpleNamespace(
        display_status="in_use",
        lifecycle_state="in_service",
        condition="in_maintenance",
        acquisition_price=Decimal("499.00"),
        acquisition_currency="USD",
    )
    assert EquipmentSerializer().get_display_status(equipment) == {"value": "in_use", "label": "In use"}
    assert EquipmentSerializer().get_lifecycle_state(equipment) == {"value": "in_service", "label": "In service"}
    assert EquipmentSerializer().get_condition(equipment) == {"value": "in_maintenance", "label": "In maintenance"}
    assert EquipmentSerializer().get_acquisition_price(equipment) == {
        "amount": "499.00",
        "currency": "USD",
    }


def test_equipment_serializer_renders_group_as_named_reference_or_null():
    serializer = EquipmentSerializer()

    assert serializer.fields["team"].to_representation(SimpleNamespace(id=12, name="Optics")) == {
        "id": 12,
        "name": "Optics",
    }
    assert serializer.fields["team"].to_representation(None) == {}


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
            "team_id": 7,
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["kind"] == 1
    assert serializer.validated_data["manufacturer"] == 3
    assert serializer.validated_data["department"] == 6
    assert serializer.validated_data["team"] == 7

