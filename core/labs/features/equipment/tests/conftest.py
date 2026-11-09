"""Shared pytest fixtures for equipment feature tests."""

import pytest

from core.labs.models.resource.equipment.equipment import Equipment
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind


@pytest.fixture()
def equipment(db):
    category = EquipmentCategory.objects.create(
        name="Computing",
        definition="Computing equipment",
    )
    kind = EquipmentKind.objects.create(
        category=category,
        name="Computer",
    )
    return Equipment.objects.create(sku="EQ-01", kind=kind, name="Test equipment")
