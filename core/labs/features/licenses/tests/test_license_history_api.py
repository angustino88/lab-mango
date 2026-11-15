"""HTTP contract of ``GET /licenses/{id}/history``: the license's status records."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import LicenseStatusRecord
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
def license_record(db):
    return License.objects.create(
        name="CAD Suite Pro",
        sku="LIC-HIST-001",
        category=LicenseCategory.objects.create(name="Hist engineering"),
        product=LicenseProduct.objects.create(name="Hist CAD"),
        vendor=LicenseVendor.objects.create(name="Hist vendor"),
        type=LicenseType.objects.create(name="Hist floating"),
        identifier="CAD-HIST-001",
    )


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="lic-hist-coord", display_name="Coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


def _url(license_id):
    return f"/api/labs/licenses/{license_id}/history"


@pytest.mark.django_db
def test_history_lists_status_changes_newest_first_with_actor(client, coordinator, license_record):
    for value in ("assigned", "suspended"):
        changed = client.post(
            f"/api/labs/licenses/{license_record.pk}/actions/change-status",
            {"status": value, "details": {"ticket": "T-1"}},
            format="json",
        )
        assert changed.status_code == 200, changed.data

    response = client.get(_url(license_record.pk))

    assert response.status_code == 200, response.data
    rows = response.data["data"]
    assert [row["status"] for row in rows] == [
        {"value": "suspended", "label": "Suspended"},
        {"value": "assigned", "label": "Assigned"},
    ]
    assert rows[0]["metadata"] == {"ticket": "T-1"}
    assert rows[0]["license"]["id"] == license_record.pk
    assert rows[0]["actor"] == {"id": coordinator.pk, "name": "Coord"}
    assert set(rows[0]) == {"id", "license", "status", "metadata", "actor", "created_at"}
    assert response.data["meta"]["pagination"]["count"] == 2


@pytest.mark.django_db
def test_empty_history(client, license_record):
    response = client.get(_url(license_record.pk))
    assert response.status_code == 200
    assert response.data["data"] == []


@pytest.mark.django_db
def test_unknown_and_deleted_licenses_are_404(client, license_record):
    assert client.get(_url(999999)).status_code == 404
    License.objects.filter(pk=license_record.pk).update(deleted_at=timezone.now())
    assert client.get(_url(license_record.pk)).status_code == 404


@pytest.mark.django_db
def test_paginated_and_rejects_unknown_query(client, license_record):
    for value in ("assigned", "suspended", "available"):
        LicenseStatusRecord.objects.create(license=license_record, status=value)

    page = client.get(_url(license_record.pk), {"page_size": 2})

    assert page.status_code == 200, page.data
    assert len(page.data["data"]) == 2
    assert client.get(_url(license_record.pk), {"status": "assigned"}).status_code == 400


@pytest.mark.django_db
def test_needs_labs_staff(license_record):
    anonymous = APIClient()
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="lic-hist-plain"))
    assert anonymous.get(_url(license_record.pk)).status_code in (401, 403)
    assert plain.get(_url(license_record.pk)).status_code == 403


@pytest.mark.django_db
def test_query_count_does_not_grow_with_rows(client, license_record):
    def seed(count):
        for index in range(count):
            user = User.objects.create_user(username=f"lic-hist-{LicenseStatusRecord.objects.count()}-{index}")
            LicenseStatusRecord(license=license_record, status="available").save(actor=user)

    def queries():
        with CaptureQueriesContext(connection) as captured:
            assert client.get(_url(license_record.pk)).status_code == 200
        return len(captured)

    seed(1)
    client.get(_url(license_record.pk))  # warm the per-user Labs role cache
    one = queries()
    seed(5)
    assert queries() == one
