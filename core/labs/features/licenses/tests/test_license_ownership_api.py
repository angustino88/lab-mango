"""License reads return their owning department and group, without one query per row."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.labs.models import Department, Group
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from tests.factories import grant_labs_role

URL = "/api/labs/licenses"


@pytest.fixture
def client(db):
    actor = grant_labs_role(get_user_model().objects.create_user(username="license-owner-reader"), "coord")
    api = APIClient()
    api.force_authenticate(user=actor)
    return api


def _license(index: int) -> License:
    eds = Department.objects.create(name=f"EDS {index}")
    return License.objects.create(
        name=f"CAD Suite {index}",
        sku=f"LIC-OWN-{index}",
        category=LicenseCategory.objects.create(name=f"Engineering {index}"),
        product=LicenseProduct.objects.create(name=f"CAD {index}"),
        vendor=LicenseVendor.objects.create(name=f"Vendor {index}"),
        type=LicenseType.objects.create(name=f"Floating {index}"),
        identifier=f"CAD-{index}",
        department=eds,
        group=Group.objects.create(name=f"EDS{index}", department=eds),
    )


def test_license_list_and_detail_return_department_and_group(client):
    record = _license(1)

    listed = client.get(URL)
    detail = client.get(f"{URL}/{record.pk}")

    assert listed.status_code == 200, listed.data
    row = next(item for item in listed.data["data"] if item["id"] == record.pk)
    expected = {"id": record.group_id, "name": "EDS1"}
    assert row["department"] == {"id": record.department_id, "name": "EDS 1"}
    assert row["group"] == expected
    assert detail.status_code == 200, detail.data
    assert detail.data["data"]["group"] == expected


def test_license_list_without_group_returns_null(client):
    record = _license(1)
    License.objects.filter(pk=record.pk).update(group=None)

    row = next(item for item in client.get(URL).data["data"] if item["id"] == record.pk)

    assert row["group"] is None


def test_license_list_query_count_does_not_grow_with_rows(client, django_assert_max_num_queries):
    _license(1)
    with django_assert_max_num_queries(50) as one_row:
        client.get(URL)
    for index in range(2, 5):
        _license(index)

    with django_assert_max_num_queries(len(one_row.captured_queries)):
        response = client.get(URL)

    assert len(response.data["data"]) == 4
