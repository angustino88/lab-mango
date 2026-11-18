"""A license is never 'unknown': it starts available, follows its seats, and keeps manual holds."""

import pytest
from rest_framework.test import APIClient

from core.labs.features.licenses.application.assignments import (
    AssignLicenseInput,
    UnassignLicenseInput,
    assign_license,
    unassign_license,
)
from core.labs.features.licenses.application.status import ChangeLicenseStatusInput, change_license_status
from core.labs.features.licenses.queries.selectors import get_license
from core.labs.features.licenses.queries.summaries import get_license_status_summary
from core.labs.models import Equipment, License, LicenseAssignment, LicenseStatusRecord
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from core.labs.models.resource.license.license import LicenseCategory, LicenseProduct, LicenseType, LicenseVendor
from tests.factories import UserFactory, grant_labs_role


@pytest.fixture
def catalog(db):
    vendor = LicenseVendor.objects.create(name="Vector")
    return {
        "category": LicenseCategory.objects.create(name="Software"),
        "product": LicenseProduct.objects.create(name="CANalyzer", vendor=vendor),
        "vendor": vendor,
        "type": LicenseType.objects.create(name="Node-locked"),
    }


@pytest.fixture
def coordinator(db):
    return grant_labs_role(UserFactory(), "coord")


@pytest.fixture
def computers(db):
    category = EquipmentCategory.objects.create(name="Computing", key="computing", definition="Computers")
    kind = EquipmentKind.objects.create(category=category, name="PC")
    return [Equipment.objects.create(name=f"COMPUTER-0{i}", sku=f"COMP-0{i}", kind=kind) for i in (1, 2)]


def _status(license_id):
    return get_license(license_id=license_id).current_status


def _new_license(catalog, sku="LIC-01", seats=2):
    # Created like the data imported before initial records existed: no status record.
    return License.objects.create(name=sku, sku=sku, seats=seats, **catalog)


@pytest.mark.django_db
def test_create_through_the_api_starts_available(catalog, coordinator):
    client = APIClient()
    client.force_authenticate(user=coordinator)
    body = {
        "sku": "LIC-NEW",
        "name": "LIC-NEW",
        "product_id": catalog["product"].pk,
        "vendor_id": catalog["vendor"].pk,
        "category_id": catalog["category"].pk,
        "type_id": catalog["type"].pk,
    }
    response = client.post("/api/labs/licenses", body, format="json")

    assert response.status_code == 201, response.data
    assert response.data["data"]["status"] == {"value": "available", "label": "Available"}
    assert list(
        LicenseStatusRecord.objects.filter(license_id=response.data["data"]["id"]).values_list("status", flat=True)
    ) == ["available"]


@pytest.mark.django_db
def test_a_license_without_records_reads_from_its_seats(catalog, computers, coordinator):
    free = _new_license(catalog, "LIC-01")
    held = _new_license(catalog, "LIC-02")
    LicenseAssignment.objects.create(license=held, equipment=computers[0])

    assert _status(free.pk) == "available"
    assert _status(held.pk) == "assigned"
    summary = {row["status"]["value"]: row["resource_count"] for row in get_license_status_summary()["statuses"]}
    assert (summary["available"], summary["assigned"]) == (1, 1)
    assert get_license_status_summary()["unknown_status_count"] == 0


@pytest.mark.django_db
def test_status_follows_the_seats(catalog, computers, coordinator):
    lic = _new_license(catalog)
    first, second = (AssignLicenseInput(equipment_id=c.pk, license_id=lic.pk) for c in computers)

    assign_license(first, actor=coordinator)
    assert _status(lic.pk) == "assigned"
    assign_license(second, actor=coordinator)
    unassign_license(UnassignLicenseInput(equipment_id=computers[0].pk, license_id=lic.pk), actor=coordinator)
    assert _status(lic.pk) == "assigned"  # one seat still held
    unassign_license(UnassignLicenseInput(equipment_id=computers[1].pk, license_id=lic.pk), actor=coordinator)
    assert _status(lic.pk) == "available"
    # One record per change, none for the second assign or the first release.
    assert list(lic.status_records.order_by("created", "id").values_list("status", flat=True)) == [
        "assigned",
        "available",
    ]


@pytest.mark.django_db
def test_seat_changes_never_override_a_manual_hold(catalog, computers, coordinator):
    lic = _new_license(catalog)
    change_license_status(ChangeLicenseStatusInput(license_id=lic.pk, status="suspended"), actor=coordinator)

    assign_license(AssignLicenseInput(equipment_id=computers[0].pk, license_id=lic.pk), actor=coordinator)
    unassign_license(UnassignLicenseInput(equipment_id=computers[0].pk, license_id=lic.pk), actor=coordinator)

    assert _status(lic.pk) == "suspended"
