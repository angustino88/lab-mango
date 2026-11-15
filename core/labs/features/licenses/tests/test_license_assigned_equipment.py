"""``assigned_equipment`` on license reads: who holds the seats, without a query per license."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import Equipment
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from core.users.models import User
from tests.factories import grant_labs_role


@pytest.fixture
def catalog(db):
    return {
        "category": LicenseCategory.objects.create(name="Assigned category"),
        "product": LicenseProduct.objects.create(name="Assigned product"),
        "vendor": LicenseVendor.objects.create(name="Assigned vendor"),
        "type": LicenseType.objects.create(name="Assigned type"),
    }


@pytest.fixture
def client(db):
    result = APIClient()
    result.force_authenticate(grant_labs_role(User.objects.create_user(username="lic-assigned"), "coord"))
    return result


@pytest.fixture
def kind(db):
    category = EquipmentCategory.objects.create(name="Assigned devices", definition="Devices")
    return EquipmentKind.objects.create(category=category, name="Assigned kind")


def _license(catalog, sku, seats=2):
    return License.objects.create(sku=sku, name=sku, seats=seats, identifier="KEY", **catalog)


def _equipment(kind, sku):
    return Equipment.objects.create(name=f"Device {sku}", sku=sku, kind=kind)


def _assign(client, license_record, equipment):
    return client.post(
        f"/api/labs/licenses/{license_record.pk}/actions/assign", {"equipment_id": equipment.pk}, format="json"
    )


@pytest.mark.django_db
def test_assigned_equipment_follows_assign_and_unassign(client, catalog, kind):
    license_record = _license(catalog, "LIC-AE-1")
    first, second = _equipment(kind, "EQ-AE-1"), _equipment(kind, "EQ-AE-2")
    assert client.get(f"/api/labs/licenses/{license_record.pk}").data["data"]["assigned_equipment"] == []

    assert _assign(client, license_record, first).status_code == 200
    assert _assign(client, license_record, second).status_code == 200
    detail = client.get(f"/api/labs/licenses/{license_record.pk}").data["data"]
    assert [item["id"] for item in detail["assigned_equipment"]] == [first.pk, second.pk]
    assert detail["assigned_equipment"][0]["name"] == "Device EQ-AE-1"
    assert detail["assigned_equipment"][0]["sku"] == "EQ-AE-1"
    assert set(detail["assigned_equipment"][0]) == {"id", "uid", "sku", "name"}
    assert detail["seats_in_use"] == 2

    released = client.delete(
        f"/api/labs/licenses/{license_record.pk}/actions/assign", {"equipment_id": first.pk}, format="json"
    )
    assert released.status_code == 204
    after = client.get(f"/api/labs/licenses/{license_record.pk}").data["data"]
    assert [item["id"] for item in after["assigned_equipment"]] == [second.pk]


@pytest.mark.django_db
def test_list_shows_each_licenses_own_equipment_and_hides_deleted_equipment(client, catalog, kind):
    one, two = _license(catalog, "LIC-AE-LIST-1"), _license(catalog, "LIC-AE-LIST-2")
    live, gone = _equipment(kind, "EQ-AE-LIVE"), _equipment(kind, "EQ-AE-GONE")
    _assign(client, one, live)
    _assign(client, one, gone)
    gone.deleted_at = timezone.now()
    gone.save(update_fields=["deleted_at"])

    rows = {row["sku"]: row for row in client.get("/api/labs/licenses").data["data"]}

    assert [item["id"] for item in rows["LIC-AE-LIST-1"]["assigned_equipment"]] == [live.pk]
    assert rows["LIC-AE-LIST-2"]["assigned_equipment"] == []
    assert two.pk  # the second license exists and is empty


@pytest.mark.django_db
def test_list_query_count_does_not_grow_with_the_number_of_licenses(client, catalog, kind):
    def count_queries():
        with CaptureQueriesContext(connection) as captured:
            assert client.get("/api/labs/licenses").status_code == 200
        return len(captured)

    first = _license(catalog, "LIC-AE-Q-1")
    _assign(client, first, _equipment(kind, "EQ-AE-Q-1"))
    baseline = count_queries()
    for index in range(2, 6):
        extra = _license(catalog, f"LIC-AE-Q-{index}")
        _assign(client, extra, _equipment(kind, f"EQ-AE-Q-{index}"))

    assert count_queries() == baseline


@pytest.mark.django_db
def test_assigning_beyond_the_seats_is_refused_cleanly(client, catalog, kind):
    license_record = _license(catalog, "LIC-AE-SEATS", seats=1)
    _assign(client, license_record, _equipment(kind, "EQ-AE-S1"))

    response = _assign(client, license_record, _equipment(kind, "EQ-AE-S2"))

    assert response.status_code == 409
    assert response.data["error"]["code"] == "license_conflict"
    assert len(client.get(f"/api/labs/licenses/{license_record.pk}").data["data"]["assigned_equipment"]) == 1
