"""Tests for licenses selector and catalog endpoints (ADR 002)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseRestriction,
    LicenseType,
    LicenseVendor,
)
from tests.factories import grant_labs_role


@pytest.fixture()
def actor(db):
    return get_user_model().objects.create_user(username="lic_actor", email="lic@example.com")


@pytest.fixture()
def client(actor):
    c = APIClient()
    grant_labs_role(actor, "coord")
    c.force_authenticate(user=actor)
    return c


@pytest.mark.django_db
def test_license_vendor_options(client):
    v = LicenseVendor.objects.create(name="JetBrains")

    # Empty filter returns all
    assert client.get("/api/labs/license-vendors/options").status_code == status.HTTP_200_OK

    resp = client.get("/api/labs/license-vendors/options?q=Jet")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"] == [{"id": v.pk, "sku": None, "name": "JetBrains"}]


@pytest.mark.django_db
def test_license_product_options(client):
    v = LicenseVendor.objects.create(name="Microsoft")
    p = LicenseProduct.objects.create(name="Visual Studio", vendor=v)

    # Empty filter returns all
    assert client.get("/api/labs/license-products/options").status_code == status.HTTP_200_OK

    # Filter with vendor_id
    resp_v = client.get(f"/api/labs/license-products/options?vendor_id={v.pk}")
    assert resp_v.status_code == status.HTTP_200_OK
    resp_data = resp_v.data["data"]
    assert any(item["name"] == "Visual Studio" for item in resp_data)

    # Filter with q
    resp_q = client.get("/api/labs/license-products/options?q=Visual")
    assert resp_q.status_code == status.HTTP_200_OK
    assert resp_q.data["data"] == [{"id": p.pk, "sku": None, "name": "Visual Studio"}]


@pytest.mark.django_db
def test_small_license_lookups_options(client):
    ltype = LicenseType.objects.create(name="Subscription")
    cat = LicenseCategory.objects.create(name="Development")
    restr = LicenseRestriction.objects.create(name="Internal Only")

    resp_type = client.get("/api/labs/license-types/options")
    assert resp_type.status_code == status.HTTP_200_OK
    assert resp_type.data["data"] == [{"id": ltype.pk, "sku": None, "name": "Subscription"}]

    resp_cat = client.get("/api/labs/license-categories/options")
    assert resp_cat.status_code == status.HTTP_200_OK
    assert resp_cat.data["data"] == [{"id": cat.pk, "sku": None, "name": "Development"}]

    resp_restr = client.get("/api/labs/license-restrictions/options")
    assert resp_restr.status_code == status.HTTP_200_OK
    assert resp_restr.data["data"] == [{"id": restr.pk, "sku": None, "name": "Internal Only"}]
