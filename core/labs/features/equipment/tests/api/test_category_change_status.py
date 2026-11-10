"""Behavioral tests for equipment category change-status action endpoints."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import Bench
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.computing import ComputingEquipment
from core.labs.models.resource.equipment.display import DisplayEquipment
from core.labs.models.resource.equipment.equipment import EquipmentStatus, EquipmentStatusRecord
from core.labs.models.resource.equipment.reference_data import EquipmentCategory, EquipmentKind


@pytest.fixture()
def api_client():
    return APIClient()


@pytest.fixture()
def actor(db):
    User = get_user_model()
    user = User.objects.create_user(username="equipment_status_actor", email="status_actor@example.com")
    return grant_labs_role(user, "coord")


@pytest.fixture()
def computing_category(db):
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    return category, kind


@pytest.fixture()
def computing_equipment(db, computing_category):
    _, kind = computing_category
    return ComputingEquipment.objects.create(
        sku="COMP-001",
        name="Computing Device 1",
        kind=kind,
        ip_address="192.168.1.100",
    )


@pytest.fixture()
def display_category(db):
    category = EquipmentCategory.objects.create(name="Display", definition="Display equipment")
    kind = EquipmentKind.objects.create(category=category, name="Monitor")
    return category, kind


@pytest.fixture()
def display_equipment(db, display_category):
    _, kind = display_category
    return DisplayEquipment.objects.create(
        sku="DISP-001",
        name="Display Device 1",
        kind=kind,
    )


@pytest.fixture()
def bench(db):
    return Bench.objects.create(name="Bench 1", sku="BENCH-01")


@pytest.fixture()
def another_bench(db):
    return Bench.objects.create(name="Bench 2", sku="BENCH-02")


@pytest.mark.django_db
def test_unauthenticated_change_status_rejected(api_client, computing_equipment):
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    response = api_client.post(
        url,
        {"status": EquipmentStatus.AVAILABLE, "details": {"responsible_person": "Ops"}},
        format="json",
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_change_status_happy_path(api_client, actor, computing_equipment):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    payload = {
        "status": EquipmentStatus.AVAILABLE,
        "details": {"responsible_person": "Alice", "notes": "Verified and tested"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    data = response.data["data"]
    assert data["id"] == computing_equipment.pk
    assert data["sku"] == "COMP-001"
    assert data["name"] == "Computing Device 1"
    assert data["status"] == {"value": "available", "label": "Available"}

    status_record = EquipmentStatusRecord.objects.filter(equipment_id=computing_equipment.pk).latest("id")
    assert status_record.status == EquipmentStatus.AVAILABLE
    assert status_record.creator == actor
    assert status_record.metadata.get("responsible_person") == "Alice"


@pytest.mark.django_db
def test_change_status_to_in_use_with_bench(api_client, actor, computing_equipment, bench):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    payload = {
        "status": EquipmentStatus.IN_USE,
        "details": {"bench_id": bench.pk, "responsible_person": "Bob"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["data"]["status"] == {"value": "in_use", "label": "In-use"}

    assignment = EquipmentAssignment.objects.filter(
        equipment_id=computing_equipment.pk,
        unassigned_at__isnull=True,
    ).first()
    assert assignment is not None
    assert assignment.bench_id == bench.pk


@pytest.mark.django_db
def test_change_status_in_use_already_assigned_different_bench_returns_conflict(
    api_client, actor, computing_equipment, bench, another_bench
):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"

    # First assignment to bench
    first_resp = api_client.post(
        url,
        {"status": EquipmentStatus.IN_USE, "details": {"bench_id": bench.pk, "responsible_person": "Bob"}},
        format="json",
    )
    assert first_resp.status_code == status.HTTP_200_OK

    # Attempt re-assignment directly to another bench via change-status without unassigning
    conflict_resp = api_client.post(
        url,
        {"status": EquipmentStatus.IN_USE, "details": {"bench_id": another_bench.pk, "responsible_person": "Charlie"}},
        format="json",
    )
    assert conflict_resp.status_code == status.HTTP_409_CONFLICT
    assert conflict_resp.data["error"]["code"] == "invalid_state_transition"


@pytest.mark.django_db
def test_change_status_in_use_missing_bench_returns_validation_error(api_client, actor, computing_equipment):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    payload = {
        "status": EquipmentStatus.IN_USE,
        "details": {"responsible_person": "Charlie"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY)
    assert "error" in response.data


@pytest.mark.django_db
def test_change_status_with_nonexistent_bench_returns_not_found(api_client, actor, computing_equipment):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    payload = {
        "status": EquipmentStatus.IN_USE,
        "details": {"bench_id": 999999, "responsible_person": "Dave"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_change_status_nonexistent_equipment_returns_not_found(api_client, actor):
    api_client.force_authenticate(user=actor)
    url = "/api/labs/equipment/computing/999999/actions/change-status"
    payload = {
        "status": EquipmentStatus.AVAILABLE,
        "details": {"responsible_person": "Eve"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_change_status_cross_category_isolation_returns_not_found(api_client, actor, display_equipment):
    api_client.force_authenticate(user=actor)
    # Target is a DisplayEquipment, accessed through the computing endpoint
    url = f"/api/labs/equipment/computing/{display_equipment.pk}/actions/change-status"
    payload = {
        "status": EquipmentStatus.AVAILABLE,
        "details": {"responsible_person": "Frank"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_change_status_soft_deleted_equipment_returns_not_found(api_client, actor, computing_equipment):
    api_client.force_authenticate(user=actor)
    computing_equipment.deleted_at = timezone.now()
    computing_equipment.save(update_fields=["deleted_at"])

    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    payload = {
        "status": EquipmentStatus.AVAILABLE,
        "details": {"responsible_person": "Grace"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_change_status_invalid_status_value_returns_validation_error(api_client, actor, computing_equipment):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    payload = {
        "status": "not_a_valid_status",
        "details": {"responsible_person": "Heidi"},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY)
    assert "error" in response.data


@pytest.mark.django_db
def test_change_status_missing_required_details_returns_validation_error(api_client, actor, computing_equipment):
    api_client.force_authenticate(user=actor)
    url = f"/api/labs/equipment/computing/{computing_equipment.pk}/actions/change-status"
    # Borrowed requires borrower and expected_return_date
    payload = {
        "status": EquipmentStatus.BORROWED,
        "details": {},
    }
    response = api_client.post(url, payload, format="json")

    assert response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY)
    assert "error" in response.data
