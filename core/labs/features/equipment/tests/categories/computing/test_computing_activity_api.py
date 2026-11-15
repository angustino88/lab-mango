"""API tests for computing equipment activity: detail projection and the activity endpoint."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.models import ComputingActivity
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from tests.factories import create_computing_equipment

_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"


@pytest.fixture()
def computing(db):
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    return create_computing_equipment(sku="COMP-API-1", name="Host API", kind=kind)


@pytest.fixture()
def admin_client(db):
    user = get_user_model().objects.create_superuser(username="act_admin", email="act@example.com", password="x")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture()
def plain_client(db):
    user = get_user_model().objects.create_user(username="act_plain", email="plain@example.com")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(equipment_id):
    return f"/api/labs/equipment/{equipment_id}/activity"


def test_unauthenticated_requests_are_rejected(computing):
    assert APIClient().get(_url(computing.pk)).status_code == status.HTTP_401_UNAUTHORIZED


def test_get_returns_offline_default_without_creating_a_row(admin_client, computing):
    response = admin_client.get(_url(computing.pk))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["status"]["value"] == "offline"
    assert not ComputingActivity.objects.filter(computing=computing).exists()


def test_get_unknown_unit_is_not_found(admin_client):
    assert admin_client.get(_url(999999)).status_code == status.HTTP_404_NOT_FOUND


def test_engineer_cannot_read_activity(plain_client, computing):
    """Equipment is visible to coordinators only (R4); activity follows it."""
    assert plain_client.get(_url(computing.pk)).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize("method", ["patch", "put", "post"])
def test_activity_is_read_only_here_even_for_coordinators_and_api_keys(admin_client, computing, method):
    """Agents report through PATCH /agent/equipment/activity (owner decision 2026-11-11)."""
    response = getattr(admin_client, method)(_url(computing.pk), {"status": "free"}, format="json")
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    with patch(_PATCH_APIKEY, return_value=True):
        keyed = getattr(APIClient(), method)(_url(computing.pk), {"status": "free"}, format="json")
    assert keyed.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert not ComputingActivity.objects.filter(computing=computing).exists()


def test_computing_detail_includes_activity(admin_client, computing):
    ComputingActivity.objects.create(computing=computing, status="active", remote_user="alice")

    response = admin_client.get(f"/api/labs/equipment/{computing.pk}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["activity"]["status"]["value"] == "active"
    assert response.json()["data"]["activity"]["remote_user"] == "alice"


def test_computing_detail_activity_is_null_when_never_reported(admin_client, computing):
    response = admin_client.get(f"/api/labs/equipment/{computing.pk}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["activity"] is None


def test_activity_is_a_detail_only_projection():
    from django.urls import resolve

    urlconf = "core.labs.features.equipment.api.urls"
    list_view = resolve("/equipment", urlconf=urlconf).func.view_class
    detail_view = resolve("/equipment/42", urlconf=urlconf).func.view_class

    assert "activity" not in list_view.list_serializer_class().get_fields()
    assert "activity" in detail_view.response_serializer_class().get_fields()
    assert "activity" in detail_view.queryset_provider().query.select_related
