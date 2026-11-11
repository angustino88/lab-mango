"""API tests for computing equipment activity: detail projection and the activity endpoint."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.models import ComputingActivity
from core.labs.models.resource.equipment.computing import ComputingEquipment
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind
from core.users.models import URSGroup

_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"


@pytest.fixture()
def computing(db):
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    return ComputingEquipment.objects.create(sku="COMP-API-1", name="Host API", kind=kind)


@pytest.fixture()
def admin_client(db):
    user = get_user_model().objects.create_superuser(username="act_admin", email="act@example.com", password="x")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture()
def plain_client(db):
    user = get_user_model().objects.create_user(username="act_plain", email="plain@example.com")
    group = Group.objects.create(name="act-plain-users")
    URSGroup.objects.create(group=group, urs_group_id=310001, labs_role="user")
    user.groups.add(group)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(sku):
    return f"/api/labs/equipment/computing/sku/{sku}/activity"


def test_unauthenticated_requests_are_rejected(computing):
    client = APIClient()

    assert client.get(_url(computing.sku)).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.patch(_url(computing.sku), {"status": "free"}, format="json").status_code == 401


def test_get_returns_offline_default_without_creating_a_row(admin_client, computing):
    response = admin_client.get(_url(computing.sku))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["status"] == "offline"
    assert not ComputingActivity.objects.filter(computing=computing).exists()


def test_get_unknown_sku_is_not_found(admin_client):
    assert admin_client.get(_url("NOPE")).status_code == status.HTTP_404_NOT_FOUND


def test_plain_lab_user_can_neither_read_nor_write(plain_client, computing):
    # Equipment is for lab coordinators and admins; plain users see it only through the dashboard.
    assert plain_client.get(_url(computing.sku)).status_code == status.HTTP_403_FORBIDDEN

    response = plain_client.patch(_url(computing.sku), {"status": "active"}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not ComputingActivity.objects.filter(computing=computing).exists()


def test_user_without_labs_role_cannot_read(db, computing):
    user = get_user_model().objects.create_user(username="act_norole", email="norole@example.com")
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get(_url(computing.sku)).status_code == status.HTTP_403_FORBIDDEN


def test_coordinator_patch_updates_activity(admin_client, computing):
    response = admin_client.patch(
        _url(computing.sku),
        {"status": "active", "remote_user": "alice", "remote_ip": "10.0.0.5"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["status"] == "active"
    assert data["remote_user"] == "alice"
    activity = ComputingActivity.objects.get(computing=computing)
    assert activity.status == "active"
    assert activity.last_agent_report_at is None


def test_api_key_agent_can_report_activity(computing):
    client = APIClient()

    with patch(_PATCH_APIKEY, return_value=True):
        response = client.patch(_url(computing.sku), {"status": "free"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    activity = ComputingActivity.objects.get(computing=computing)
    assert activity.status == "free"
    assert activity.last_agent_report_at is not None


def test_agent_api_error_does_not_persist_activity_or_heartbeat(computing):
    client = APIClient()

    with patch(_PATCH_APIKEY, return_value=True):
        response = client.patch(_url(computing.sku), {"status": "invalid"}, format="json")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert not ComputingActivity.objects.filter(computing=computing).exists()


def test_api_agent_report_updates_heartbeat_and_repeated_inactive_keeps_inactive_at(computing):
    client = APIClient()

    with patch(_PATCH_APIKEY, return_value=True):
        initial = client.patch(_url(computing.sku), {"status": "inactive"}, format="json")
        assert initial.status_code == status.HTTP_200_OK
        activity = ComputingActivity.objects.get(computing=computing)
        initial_heartbeat = activity.last_agent_report_at
        inactive_at = activity.inactive_at

        # Move the stored heartbeat back deterministically so a successful retry must refresh it.
        stale_heartbeat = initial_heartbeat - timedelta(minutes=1)
        ComputingActivity.objects.filter(pk=activity.pk).update(last_agent_report_at=stale_heartbeat)
        repeated = client.patch(_url(computing.sku), {"status": "inactive"}, format="json")

    assert repeated.status_code == status.HTTP_200_OK
    activity.refresh_from_db()
    assert activity.inactive_at == inactive_at
    assert activity.last_agent_report_at > stale_heartbeat


def test_patch_rejects_invalid_status_and_server_managed_fields(admin_client, computing):
    bad_status = admin_client.patch(_url(computing.sku), {"status": "exploded"}, format="json")
    managed = admin_client.patch(_url(computing.sku), {"offline_at": "2026-01-01T00:00:00Z"}, format="json")

    assert bad_status.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert managed.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert managed.json()["error"]["details"][0]["code"] == "read_only_field"
    assert not ComputingActivity.objects.filter(computing=computing).exists()


@pytest.mark.parametrize("field", ("offline_at", "inactive_at"))
def test_patch_rejects_each_transition_timestamp_as_read_only(admin_client, computing, field):
    response = admin_client.patch(_url(computing.sku), {field: "2026-01-01T00:00:00Z"}, format="json")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert any(
        error["field"] == field and error["code"] == "read_only_field" for error in response.json()["error"]["details"]
    )
    assert not ComputingActivity.objects.filter(computing=computing).exists()


def test_patch_unknown_sku_is_not_found(admin_client):
    response = admin_client.patch(_url("NOPE"), {"status": "free"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_computing_detail_includes_activity(admin_client, computing):
    ComputingActivity.objects.create(computing=computing, status="active", remote_user="alice")

    response = admin_client.get(f"/api/labs/equipment/computing/{computing.pk}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["activity"]["status"] == "active"
    assert response.json()["data"]["activity"]["remote_user"] == "alice"


def test_computing_detail_activity_is_null_when_never_reported(admin_client, computing):
    response = admin_client.get(f"/api/labs/equipment/computing/{computing.pk}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"]["activity"] is None


def test_activity_is_a_detail_only_projection():
    from django.urls import resolve

    urlconf = "core.labs.features.equipment.api.urls"
    list_view = resolve("/equipment/computing", urlconf=urlconf).func.view_class
    detail_view = resolve("/equipment/computing/42", urlconf=urlconf).func.view_class

    assert "activity" not in list_view.list_serializer_class().get_fields()
    assert "activity" in detail_view.response_serializer_class().get_fields()
    assert "activity" in detail_view.queryset_provider().query.select_related
