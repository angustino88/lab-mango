"""HTTP contract of ``POST /licenses``, ``PATCH /licenses/{id}`` and ``DELETE /licenses/{id}``."""

import pytest
from rest_framework.test import APIClient

from core.labs.features.licenses.application.assignments import AssignLicenseInput, assign_license
from core.labs.models import Department, Equipment, Group, License
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from core.users.models import User
from tests.factories import grant_labs_role

LIST_URL = "/api/labs/licenses"


@pytest.fixture
def catalog(db):
    vendor = LicenseVendor.objects.create(name="Write vendor")
    return {
        "vendor": vendor,
        "other_vendor": LicenseVendor.objects.create(name="Other write vendor"),
        "product": LicenseProduct.objects.create(name="Write product", vendor=vendor),
        "type": LicenseType.objects.create(name="Write floating"),
        "category": LicenseCategory.objects.create(name="Write engineering"),
    }


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="lic-write-coord", display_name="Coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


def _body(catalog, **overrides):
    body = {
        "sku": "LIC-WRITE-001",
        "name": "CAD Suite Pro",
        "product_id": catalog["product"].pk,
        "vendor_id": catalog["vendor"].pk,
        "type_id": catalog["type"].pk,
        "category_id": catalog["category"].pk,
        "seats": 3,
        "max_version": "2026.1",
        "identifier": "SECRET-KEY-123",
        "expires_at": "2027-01-31T00:00:00Z",
    }
    body.update(overrides)
    return body


def _create(client, catalog, **overrides):
    response = client.post(LIST_URL, _body(catalog, **overrides), format="json")
    assert response.status_code == 201, response.data
    return response


@pytest.fixture
def equipment(db):
    category = EquipmentCategory.objects.create(name="Write measurement", definition="Devices")
    kind = EquipmentKind.objects.create(category=category, name="Write scope")
    return Equipment.objects.create(name="Write oscilloscope", sku="EQ-LIC-WRITE-1", kind=kind)


@pytest.fixture
def second_equipment(db, equipment):
    return Equipment.objects.create(name="Write analyser", sku="EQ-LIC-WRITE-2", kind=equipment.kind)


@pytest.mark.django_db
def test_create_returns_the_license_and_never_the_key(client, catalog):
    response = _create(client, catalog)
    data = response.data["data"]

    assert data["sku"] == "LIC-WRITE-001"
    assert data["seats"] == 3
    assert data["max_version"] == "2026.1"
    assert data["vendor"]["id"] == catalog["vendor"].pk
    assert data["expires_at"].startswith("2027-01-31")
    assert "identifier" not in data
    assert "SECRET-KEY-123" not in str(response.content)
    assert License.objects.get(pk=data["id"]).identifier == "SECRET-KEY-123"


@pytest.mark.django_db
def test_license_ownership_is_returned_and_can_be_cleared(client, catalog):
    department = Department.objects.create(name="License department")
    group = Group.objects.create(name="License group", department=department)
    created = _create(client, catalog, department_id=department.pk, group_id=group.pk).data["data"]
    assert created["department"] == {"id": department.pk, "name": department.name}
    assert created["group"] == {"id": group.pk, "name": group.name}

    url = f"{LIST_URL}/{created['id']}"
    response = client.patch(url, {"department_id": None, "group_id": None}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["data"]["department"] is None
    assert response.data["data"]["group"] is None


@pytest.mark.django_db
def test_create_requires_sku_and_the_four_catalog_references(client, catalog):
    response = client.post(LIST_URL, {"name": "Missing everything"}, format="json")

    assert response.status_code == 422
    fields = {error["field"] for error in response.data["error"]["details"]}
    assert {"product_id", "vendor_id", "type_id", "category_id"} <= fields


@pytest.mark.django_db
def test_create_rejects_an_unknown_reference_and_a_product_vendor_mismatch(client, catalog):
    unknown = client.post(LIST_URL, _body(catalog, type_id=999999), format="json")
    mismatch = client.post(
        LIST_URL, _body(catalog, sku="LIC-WRITE-002", vendor_id=catalog["other_vendor"].pk), format="json"
    )

    assert unknown.status_code == 422
    assert mismatch.status_code == 422
    assert not License.objects.filter(sku="LIC-WRITE-002").exists()


@pytest.mark.django_db
def test_create_rejects_unknown_fields_and_bad_seats(client, catalog):
    assert client.post(LIST_URL, _body(catalog, bogus=1), format="json").status_code == 422
    assert client.post(LIST_URL, _body(catalog, seats=0), format="json").status_code == 422


@pytest.mark.django_db
def test_duplicate_sku_among_live_licenses_is_a_conflict(client, catalog):
    _create(client, catalog)

    response = client.post(LIST_URL, _body(catalog), format="json")

    assert response.status_code == 409


@pytest.mark.django_db
def test_plain_users_and_anonymous_callers_cannot_write(catalog):
    anonymous = APIClient().post(LIST_URL, _body(catalog), format="json")
    member = APIClient()
    member.force_authenticate(grant_labs_role(User.objects.create_user(username="lic-write-member"), "member"))

    assert anonymous.status_code in (401, 403)
    assert member.post(LIST_URL, _body(catalog), format="json").status_code == 403


@pytest.mark.django_db
def test_patch_changes_fields_and_keeps_the_key_hidden(client, catalog):
    license_id = _create(client, catalog).data["data"]["id"]

    response = client.patch(
        f"{LIST_URL}/{license_id}",
        {"name": "CAD Suite Plus", "seats": 5, "expires_at": None, "identifier": "ROTATED-KEY"},
        format="json",
    )

    assert response.status_code == 200, response.data
    data = response.data["data"]
    assert (data["name"], data["seats"], data["expires_at"]) == ("CAD Suite Plus", 5, None)
    assert "identifier" not in data
    assert License.objects.get(pk=license_id).identifier == "ROTATED-KEY"


@pytest.mark.django_db
def test_patch_cannot_change_the_sku(client, catalog):
    license_id = _create(client, catalog).data["data"]["id"]

    response = client.patch(f"{LIST_URL}/{license_id}", {"sku": "LIC-OTHER"}, format="json")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "resource_field_immutable"
    assert License.objects.get(pk=license_id).sku == "LIC-WRITE-001"


@pytest.mark.django_db
def test_patch_cannot_reduce_seats_below_the_seats_in_use(client, catalog, equipment, second_equipment, coordinator):
    created = _create(client, catalog, seats=2).data["data"]
    license_record = License.objects.get(pk=created["id"])
    for item in (equipment, second_equipment):
        assign_license(AssignLicenseInput(equipment_id=item.pk, license_id=license_record.pk), actor=coordinator)

    too_few = client.patch(f"{LIST_URL}/{license_record.pk}", {"seats": 1}, format="json")
    enough = client.patch(f"{LIST_URL}/{license_record.pk}", {"seats": 2}, format="json")

    assert too_few.status_code == 409
    assert enough.status_code == 200


@pytest.mark.django_db
def test_patch_and_delete_of_a_missing_license_are_404(client):
    assert client.patch(f"{LIST_URL}/999999", {"name": "x"}, format="json").status_code == 404
    assert client.delete(f"{LIST_URL}/999999").status_code == 404


@pytest.mark.django_db
def test_delete_soft_deletes_and_frees_the_sku(client, catalog):
    license_id = _create(client, catalog).data["data"]["id"]

    deleted = client.delete(f"{LIST_URL}/{license_id}")

    assert deleted.status_code == 204
    assert client.get(f"{LIST_URL}/{license_id}").status_code == 404
    assert License.all_objects.get(pk=license_id).deleted_at is not None
    assert client.post(LIST_URL, _body(catalog), format="json").status_code == 201


@pytest.mark.django_db
def test_delete_is_refused_while_the_license_is_assigned(client, catalog, equipment, coordinator):
    license_id = _create(client, catalog).data["data"]["id"]
    assign_license(AssignLicenseInput(equipment_id=equipment.pk, license_id=license_id), actor=coordinator)

    response = client.delete(f"{LIST_URL}/{license_id}")

    assert response.status_code == 409
    assert License.objects.filter(pk=license_id, deleted_at__isnull=True).exists()


@pytest.mark.django_db
def test_serial_number_is_visible_searchable_and_separate_from_the_key(client, catalog):
    created = _create(client, catalog, serial_number=" 55100045010 ").data["data"]

    assert created["serial_number"] == "55100045010"
    assert "identifier" not in created
    record = License.objects.get(pk=created["id"])
    assert (record.serial_number, record.identifier) == ("55100045010", "SECRET-KEY-123")
    found = client.get(LIST_URL, {"q": "55100045010"}).data["data"]
    assert [item["id"] for item in found] == [created["id"]]

    patched = client.patch(f"{LIST_URL}/{created['id']}", {"serial_number": "55100045011"}, format="json")
    assert patched.status_code == 200, patched.data
    assert patched.data["data"]["serial_number"] == "55100045011"


@pytest.mark.django_db
def test_a_vendor_serial_is_unique_among_live_licenses(client, catalog):
    first = _create(client, catalog, serial_number="55100045010").data["data"]

    duplicate = client.post(LIST_URL, _body(catalog, sku="LIC-WRITE-002", serial_number="55100045010"), format="json")
    assert duplicate.status_code == 409

    other_vendor_product = LicenseProduct.objects.create(name="Other product", vendor=catalog["other_vendor"])
    other_vendor = client.post(
        LIST_URL,
        _body(
            catalog,
            sku="LIC-WRITE-003",
            serial_number="55100045010",
            vendor_id=catalog["other_vendor"].pk,
            product_id=other_vendor_product.pk,
        ),
        format="json",
    )
    assert other_vendor.status_code == 201, other_vendor.data

    assert client.delete(f"{LIST_URL}/{first['id']}").status_code in (200, 204)
    reused = client.post(LIST_URL, _body(catalog, sku="LIC-WRITE-004", serial_number="55100045010"), format="json")
    assert reused.status_code == 201, reused.data
