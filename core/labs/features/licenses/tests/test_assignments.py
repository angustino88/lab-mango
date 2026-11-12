"""Tests for license assignment and unassignment commands."""

import pytest
from django.contrib.auth import get_user_model

from core.labs.features.licenses.application.assignments import (
    AssignLicenseInput,
    UnassignLicenseInput,
    assign_license,
    unassign_license,
)
from core.labs.models import Equipment, LicenseAssignment
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from tests.factories import grant_labs_role

User = get_user_model()


@pytest.fixture
def test_user(db):
    return User.objects.create_user(username="license_tester", password="password")


@pytest.fixture
def equipment(db):
    category = EquipmentCategory.objects.create(name="Measurement", definition="Measurement devices")
    kind = EquipmentKind.objects.create(category=category, name="Scope")
    return Equipment.objects.create(name="Oscilloscope", sku="EQ-TEST-001", kind=kind)


@pytest.fixture
def license_record(db):
    category = LicenseCategory.objects.create(name="Engineering")
    product = LicenseProduct.objects.create(name="CAD Suite")
    vendor = LicenseVendor.objects.create(name="Vendor X")
    type_ = LicenseType.objects.create(name="Floating")
    return License.objects.create(
        name="CAD Suite Pro",
        sku="LIC-TEST-001",
        category=category,
        product=product,
        vendor=vendor,
        type=type_,
        identifier="CAD-001",
    )


@pytest.mark.django_db
def test_assign_license_is_idempotent(equipment, license_record, test_user):
    cmd = AssignLicenseInput(equipment_id=equipment.pk, license_id=license_record.pk)

    # First assignment succeeds
    assignment1 = assign_license(cmd, actor=test_user)
    assert assignment1 is not None
    assert assignment1.equipment_id == equipment.pk
    assert assignment1.license_id == license_record.pk
    assert assignment1.unassigned_at is None

    # Replay returns the existing active assignment cleanly without raising LicenseAlreadyAssigned
    assignment2 = assign_license(cmd, actor=test_user)
    assert assignment2.pk == assignment1.pk

    # Verify only 1 active assignment row in the database
    assert (
        LicenseAssignment.objects.filter(
            equipment=equipment,
            license=license_record,
            unassigned_at__isnull=True,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_unassign_license(equipment, license_record, test_user):
    cmd_assign = AssignLicenseInput(equipment_id=equipment.pk, license_id=license_record.pk)
    assignment = assign_license(cmd_assign, actor=test_user)

    cmd_unassign = UnassignLicenseInput(equipment_id=equipment.pk, license_id=license_record.pk)
    unassigned = unassign_license(cmd_unassign, actor=test_user)
    assert unassigned is not None
    assert unassigned.pk == assignment.pk
    assert unassigned.unassigned_at is not None

    # After unassigning, assign_license can create a new active assignment
    new_assignment = assign_license(cmd_assign, actor=test_user)
    assert new_assignment.pk != assignment.pk
    assert new_assignment.unassigned_at is None


@pytest.mark.django_db
def test_delete_action_assign_unassigns_license(equipment, license_record, test_user):
    from rest_framework.test import APIClient

    client = APIClient()
    grant_labs_role(test_user, "coord")
    client.force_authenticate(user=test_user)

    cmd_assign = AssignLicenseInput(equipment_id=equipment.pk, license_id=license_record.pk)
    assign_license(cmd_assign, actor=test_user)

    resp = client.delete(
        f"/api/labs/licenses/{license_record.pk}/actions/assign",
        data={"equipment_id": equipment.pk},
        format="json",
    )
    assert resp.status_code == 204
    assert not LicenseAssignment.objects.filter(license=license_record, unassigned_at__isnull=True).exists()


@pytest.mark.django_db
def test_post_action_unassign_returns_deprecation_headers(equipment, license_record, test_user):
    from rest_framework.test import APIClient

    client = APIClient()
    grant_labs_role(test_user, "coord")
    client.force_authenticate(user=test_user)

    cmd_assign = AssignLicenseInput(equipment_id=equipment.pk, license_id=license_record.pk)
    assign_license(cmd_assign, actor=test_user)

    resp = client.post(
        f"/api/labs/licenses/{license_record.pk}/actions/unassign",
        data={"equipment_id": equipment.pk},
        format="json",
    )
    assert resp.status_code == 204
    assert resp.headers.get("Deprecation") == "true"
    assert "Sunset" in resp.headers
    assert f"/api/labs/licenses/{license_record.pk}/actions/assign" in resp.headers.get("Link", "")
