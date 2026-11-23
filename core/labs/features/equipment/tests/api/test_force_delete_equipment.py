"""Tests for equipment force-delete command and HTTP action endpoint."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import (
    Bench,
    Equipment,
    EquipmentAssignment,
    EquipmentBooking,
    EquipmentCategory,
    EquipmentKind,
    EquipmentLoan,
    EquipmentLoanBatch,
    LicenseAssignment,
    LoanCloseReason,
    ResourceChangeLog,
)
from core.labs.models.booking.base import BookingStatus
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)

User = get_user_model()
ROOT = "/api/labs/"


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="fd-coord"), "coord")


@pytest.fixture
def plain_user(db):
    return User.objects.create_user(username="fd-plain")


@pytest.fixture
def sample_unit(db):
    category = EquipmentCategory.objects.create(key="fd-samples", name="FD Samples", definition="FD Samples")
    kind = EquipmentKind.objects.create(category=category, name="FD Sample Kind")
    return Equipment.objects.create(kind=kind, sku="FD-SAMPLE-01", name="Force Delete Sample")


def _create_license(suffix: str = "1") -> License:
    return License.objects.create(
        name=f"FD License {suffix}",
        sku=f"FD-LIC-{suffix}",
        category=LicenseCategory.objects.create(name=f"FD Cat {suffix}"),
        product=LicenseProduct.objects.create(name=f"FD Prod {suffix}"),
        vendor=LicenseVendor.objects.create(name=f"FD Vendor {suffix}"),
        type=LicenseType.objects.create(name=f"FD Type {suffix}"),
        identifier=f"FD-ID-{suffix}",
        seats=2,
    )


@pytest.mark.django_db
def test_force_delete_releases_all_active_dependents_and_soft_deletes(coordinator, sample_unit):
    now = timezone.now()
    bench = Bench.objects.create(name="FD Bench", sku="FD-BENCH-1")
    assignment = EquipmentAssignment.objects.create(equipment=sample_unit, bench=bench, assigned_at=now)
    batch = EquipmentLoanBatch.objects.create(borrower_name="Alice", purpose="Testing", created_by=coordinator)
    loan = EquipmentLoan.objects.create(
        equipment=sample_unit,
        batch=batch,
        handed_over_at=now,
        handed_over_by=coordinator,
        due_at=now + timedelta(days=2),
    )
    lic1 = _create_license("A")
    lic2 = _create_license("B")
    lic_assignment_1 = LicenseAssignment.objects.create(license=lic1, equipment=sample_unit)
    lic_assignment_2 = LicenseAssignment.objects.create(license=lic2, equipment=sample_unit)
    booking = EquipmentBooking.objects.create(
        equipment=sample_unit,
        booking_code="FD-BK-1",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
    )

    # Normal delete must still refuse with 409 and list all blockers.
    normal = _client(coordinator).delete(ROOT + f"equipment/{sample_unit.pk}")
    assert normal.status_code == 409
    assert normal.data["error"]["code"] == "equipment_in_use"
    blockers = {
        item["message"] for item in normal.data["error"]["details"] if (item.get("field") or "").startswith("blockers")
    }
    assert blockers == {
        "bench_assignment",
        "loan",
        "license_assignment",
        "booking",
    }

    # Force delete atomically releases all dependents and soft-deletes the unit.
    response = _client(coordinator).post(
        ROOT + f"equipment/{sample_unit.pk}/actions/force-delete",
        {"reason": "Scrapped hardware unit", "confirm": True},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["data"] == {
        "id": sample_unit.pk,
        "released": {
            "bench_assignments": 1,
            "loans": 1,
            "license_assignments": 2,
            "bookings": 1,
        },
    }

    sample_unit.refresh_from_db()
    assert sample_unit.deleted_at is not None

    assignment.refresh_from_db()
    assert assignment.unassigned_at is not None

    loan.refresh_from_db()
    assert loan.returned_at is not None
    assert loan.close_reason == LoanCloseReason.RETURNED
    assert "Scrapped hardware unit" in loan.condition_in

    lic_assignment_1.refresh_from_db()
    lic_assignment_2.refresh_from_db()
    assert lic_assignment_1.unassigned_at is not None
    assert lic_assignment_2.unassigned_at is not None

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert "Scrapped hardware unit" in booking.cancellation_reason

    log = ResourceChangeLog.objects.filter(
        resource_object_id=str(sample_unit.pk),
        action=ResourceChangeLog.Action.DELETE,
        field_name="force_delete",
    ).first()
    assert log is not None
    assert log.new_value["reason"] == "Scrapped hardware unit"
    assert log.new_value["released"] == {
        "bench_assignments": 1,
        "loans": 1,
        "license_assignments": 2,
        "bookings": 1,
    }


@pytest.mark.django_db
def test_force_delete_succeeds_with_no_dependents_and_second_call_returns_404(coordinator, sample_unit):
    url = ROOT + f"equipment/{sample_unit.pk}/actions/force-delete"
    first = _client(coordinator).post(url, {"reason": "Duplicate record", "confirm": True}, format="json")
    assert first.status_code == 200, first.data
    assert first.data["data"]["released"] == {
        "bench_assignments": 0,
        "loans": 0,
        "license_assignments": 0,
        "bookings": 0,
    }

    second = _client(coordinator).post(url, {"reason": "Duplicate record", "confirm": True}, format="json")
    assert second.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "Valid reason", "confirm": False},
        {"reason": "Valid reason"},
        {"reason": "  ", "confirm": True},
        {"reason": "ab", "confirm": True},
        {"reason": "Valid reason", "confirm": True, "unexpected": "field"},
    ],
)
def test_force_delete_validation_rejects_invalid_payloads(coordinator, sample_unit, payload):
    response = _client(coordinator).post(
        ROOT + f"equipment/{sample_unit.pk}/actions/force-delete",
        payload,
        format="json",
    )
    assert response.status_code == 422, response.data
    sample_unit.refresh_from_db()
    assert sample_unit.deleted_at is None


@pytest.mark.django_db
def test_force_delete_enforces_lab_operations_permission(plain_user, sample_unit):
    url = ROOT + f"equipment/{sample_unit.pk}/actions/force-delete"
    payload = {"reason": "Unauthorized attempt", "confirm": True}

    anon = _client().post(url, payload, format="json")
    assert anon.status_code == 401

    forbidden = _client(plain_user).post(url, payload, format="json")
    assert forbidden.status_code == 403

    sample_unit.refresh_from_db()
    assert sample_unit.deleted_at is None
