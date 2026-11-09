"""Tests for automatic RDP file creation and lifecycle on ComputingEquipment."""

import pytest

from core.labs.features.equipment.application import CreateEquipmentInput, create_equipment
from core.labs.models.resource.equipment.computing import ComputingEquipment, TechnicalUser
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind


@pytest.fixture()
def computing_category(db):
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    return category, kind


@pytest.mark.django_db
def test_create_computing_equipment_generates_rdp_file(computing_category):
    _, kind = computing_category
    computing = ComputingEquipment.objects.create(
        sku="COMP-TEST-001",
        name="Host Alpha",
        kind=kind,
    )

    assert bool(computing.rdp_file)
    assert computing.rdp_file.name.endswith("COMP-TEST-001.rdp")

    content = computing.rdp_file.read()
    assert b"full address:s:COMP-TEST-001" in content
    assert b"username:s:\n" in content or content.endswith(b"username:s:")


@pytest.mark.django_db
def test_create_computing_equipment_with_technical_user(computing_category):
    _, kind = computing_category
    tech_user = TechnicalUser.objects.create(username="svc_lab_admin")
    computing = ComputingEquipment.objects.create(
        sku="COMP-TECH-002",
        name="Host Beta",
        kind=kind,
        technical_user=tech_user,
    )

    assert bool(computing.rdp_file)
    assert computing.rdp_file.name.endswith("COMP-TECH-002.rdp")

    content = computing.rdp_file.read()
    assert b"full address:s:COMP-TECH-002" in content
    assert b"username:s:svc_lab_admin" in content


@pytest.mark.django_db
def test_update_computing_equipment_sku_regenerates_rdp_file(computing_category):
    _, kind = computing_category
    computing = ComputingEquipment.objects.create(
        sku="COMP-OLD-SKU",
        name="Host Gamma",
        kind=kind,
    )

    old_file_name = computing.rdp_file.name
    storage = computing.rdp_file.storage
    assert storage.exists(old_file_name)

    computing.sku = "COMP-NEW-SKU"
    computing.save()

    assert computing.rdp_file.name.endswith("COMP-NEW-SKU.rdp")
    assert not storage.exists(old_file_name)
    assert storage.exists(computing.rdp_file.name)

    content = computing.rdp_file.read()
    assert b"full address:s:COMP-NEW-SKU" in content


@pytest.mark.django_db
def test_update_technical_user_regenerates_rdp_file(computing_category):
    _, kind = computing_category
    computing = ComputingEquipment.objects.create(
        sku="COMP-TECH-UPDATE",
        name="Host Delta",
        kind=kind,
    )

    content_initial = computing.rdp_file.read()
    assert b"username:s:tech_engineer" not in content_initial

    # Refresh instance from DB to verify from_db state tracking
    computing = ComputingEquipment.objects.get(pk=computing.pk)
    tech_user = TechnicalUser.objects.create(username="tech_engineer")
    computing.technical_user = tech_user
    computing.save()

    computing.refresh_from_db()
    content_updated = computing.rdp_file.read()
    assert b"full address:s:COMP-TECH-UPDATE" in content_updated
    assert b"username:s:tech_engineer" in content_updated


@pytest.mark.django_db
def test_non_identity_partial_update_does_not_regenerate_rdp_file(computing_category):
    _, kind = computing_category
    computing = ComputingEquipment.objects.create(
        sku="COMP-STABLE",
        name="Host Epsilon",
        kind=kind,
    )

    original_file_name = computing.rdp_file.name

    # Fetch fresh instance from DB and do a partial update on unrelated field
    computing = ComputingEquipment.objects.get(pk=computing.pk)
    computing.os_name = "Debian 12"
    computing.save(update_fields=["os_name"])

    computing.refresh_from_db()
    assert computing.os_name == "Debian 12"
    assert computing.rdp_file.name == original_file_name


@pytest.mark.django_db
def test_soft_delete_preserves_rdp_file(computing_category):
    _, kind = computing_category
    computing = ComputingEquipment.objects.create(
        sku="COMP-SOFT-DEL",
        name="Host Eta",
        kind=kind,
    )

    file_name = computing.rdp_file.name
    storage = computing.rdp_file.storage
    assert storage.exists(file_name)

    computing.delete()
    assert computing.deleted_at is not None
    assert storage.exists(file_name)


@pytest.mark.django_db
def test_hard_delete_cleans_up_rdp_file(computing_category):
    _, kind = computing_category
    computing = ComputingEquipment.objects.create(
        sku="COMP-HARD-DEL",
        name="Host Zeta",
        kind=kind,
    )

    file_name = computing.rdp_file.name
    storage = computing.rdp_file.storage
    assert storage.exists(file_name)

    computing.hard_delete()
    assert not storage.exists(file_name)


@pytest.mark.django_db
def test_create_equipment_application_command_generates_rdp_file(computing_category):
    _, kind = computing_category
    created = create_equipment(
        CreateEquipmentInput(
            fields=(
                ("kind", kind),
                ("sku", "COMP-APP-001"),
                ("name", "App Created Host"),
            )
        ),
        actor=None,
        model=ComputingEquipment,
    )

    assert bool(created.rdp_file)
    assert created.rdp_file.name.endswith("COMP-APP-001.rdp")

    content = created.rdp_file.read()
    assert b"full address:s:COMP-APP-001" in content
