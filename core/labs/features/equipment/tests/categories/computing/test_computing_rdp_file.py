"""The .rdp file of a computing unit, written by the equipment commands (redesign step 6)."""

import pytest

from core.labs.features.equipment.application import (
    CreateEquipmentInput,
    UpdateEquipmentInput,
    create_equipment,
    update_equipment,
)
from core.labs.features.equipment.application.computing_profile import sync_rdp_file
from core.labs.models import ComputingProfile
from core.labs.models.resource.equipment.computing import TechnicalUser
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from tests.factories import create_computing_equipment


@pytest.fixture()
def kind(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment", monitored=True)
    return EquipmentKind.objects.create(category=category, name="Computer")


def _create(kind, sku, **computing):
    fields = [("kind", kind), ("sku", sku), ("name", f"Host {sku}")]
    if computing:
        fields.append(("computing", computing))
    unit = create_equipment(CreateEquipmentInput(fields=tuple(fields)), actor=None)
    return unit, ComputingProfile.objects.get(equipment=unit)


def _update(unit, **fields):
    update_equipment(UpdateEquipmentInput(equipment_id=unit.pk, fields=tuple(fields.items())), actor=None)
    return ComputingProfile.objects.get(equipment=unit)


def test_create_generates_rdp_file_for_the_sku(kind):
    _, profile = _create(kind, "COMP-TEST-001")
    assert profile.rdp_file.name.endswith("COMP-TEST-001.rdp")
    content = profile.rdp_file.read()
    assert b"full address:s:COMP-TEST-001" in content
    assert b"username:s:\n" in content or content.endswith(b"username:s:")


def test_hostname_wins_over_the_sku(kind):
    _, profile = _create(kind, "COMP-HOST-001", hostname="pc-1.lab")
    assert b"full address:s:pc-1.lab" in profile.rdp_file.read()


def test_sku_change_regenerates_rdp_file(kind):
    unit, profile = _create(kind, "COMP-OLD-SKU")
    old_name, storage = profile.rdp_file.name, profile.rdp_file.storage
    profile = _update(unit, sku="COMP-NEW-SKU")
    assert profile.rdp_file.name.endswith("COMP-NEW-SKU.rdp")
    assert not storage.exists(old_name) and storage.exists(profile.rdp_file.name)
    assert b"full address:s:COMP-NEW-SKU" in profile.rdp_file.read()


def test_technical_user_change_regenerates_rdp_file(kind):
    unit, profile = _create(kind, "COMP-TECH-UPDATE")
    assert b"username:s:tech_engineer" not in profile.rdp_file.read()
    tech_user = TechnicalUser.objects.create(username="tech_engineer")
    profile = _update(unit, computing={"technical_user": tech_user})
    content = profile.rdp_file.read()
    assert b"full address:s:COMP-TECH-UPDATE" in content
    assert b"username:s:tech_engineer" in content


def test_unrelated_update_keeps_the_rdp_file(kind):
    unit, profile = _create(kind, "COMP-STABLE")
    original = profile.rdp_file.name
    profile = _update(unit, name="Renamed host")
    assert profile.rdp_file.name == original


def test_soft_delete_preserves_and_hard_delete_removes_the_file(kind):
    # A unit with no state history (EquipmentEvent protects units that have one).
    unit = create_computing_equipment(sku="COMP-DEL", name="Host", kind=kind)
    profile = ComputingProfile.objects.get(equipment=unit)
    sync_rdp_file(profile)
    name, storage = profile.rdp_file.name, profile.rdp_file.storage
    unit.delete()
    assert unit.deleted_at is not None and storage.exists(name)
    unit.hard_delete()
    assert not storage.exists(name)
