"""Tests for equipment read queries."""

from datetime import UTC, datetime

import pytest

from core.labs.features.equipment.queries.equipment import (
    equipment_mapping_rows,
    get_equipment_for_mapping,
)

pytestmark = pytest.mark.django_db


def test_equipment_mapping_projection_exposes_existing_equipment_uid(equipment):
    """The mapping UID identifies the equipment resource, not an enrolled agent."""
    row = get_equipment_for_mapping(equipment_id=equipment.pk)

    assert row is not None
    assert row["id"] == equipment.pk
    assert row["uid"] == equipment.uid


def test_equipment_mapping_projection_omits_soft_deleted_equipment(equipment):
    equipment.deleted_at = datetime.now(UTC)
    equipment.save(update_fields=["deleted_at"])

    assert get_equipment_for_mapping(equipment_id=equipment.pk) is None


def test_equipment_mapping_rows_omits_soft_deleted_equipment(equipment):
    equipment.deleted_at = datetime.now(UTC)
    equipment.save(update_fields=["deleted_at"])

    rows = equipment_mapping_rows(equipment_ids=[equipment.pk])

    assert list(rows) == []
