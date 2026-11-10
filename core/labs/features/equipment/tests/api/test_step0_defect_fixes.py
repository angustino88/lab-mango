"""Regression tests for equipment redesign Step 0 (defects D1 to D5).

See docs/proposals/equipment-management-redesign.md, "Confirmed defects".
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.application import DeleteEquipmentInput, delete_equipment
from core.labs.features.equipment.exceptions import EquipmentInUse
from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.features.leaderboard.public import get_dashboard_summary
from core.labs.models import (
    Bench,
    ComputingActivity,
    ComputingEquipment,
    Equipment,
    EquipmentAssignment,
    EquipmentBooking,
    EquipmentCategory,
    EquipmentKind,
    LicenseAssignment,
    Room,
)
from core.labs.models.resource.license.license import (
    License,
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)

ROOT = "/api/labs/"
User = get_user_model()


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def plain_user(db):
    return User.objects.create_user(username="step0-plain")


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="step0-coord"), "coord")


@pytest.fixture
def lab_admin(db):
    return grant_labs_role(User.objects.create_user(username="step0-admin"), "admin")


@pytest.fixture
def computing_kind(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return EquipmentKind.objects.create(category=category, name="Workstation")


@pytest.fixture
def computing_unit(computing_kind):
    return ComputingEquipment.objects.create(sku="S0-COMP-1", name="Step0 PC", kind=computing_kind)


# D1: equipment writes need the coordinator role -------------------------------------------


@pytest.mark.django_db
def test_plain_user_cannot_read_or_write_equipment(plain_user, computing_kind, computing_unit):
    client = _client(plain_user)
    bench = Bench.objects.create(name="S0 bench", sku="S0-BENCH-1")
    pk = computing_unit.pk
    writes = [
        ("post", "equipment", {"kind_id": computing_kind.pk, "sku": "S0-NEW", "name": "x"}),
        ("post", "equipment/computing", {"kind_id": computing_kind.pk, "sku": "S0-NEW2", "name": "x"}),
        ("patch", f"equipment/computing/{pk}", {"name": "renamed"}),
        ("delete", f"equipment/computing/{pk}", None),
        ("patch", f"equipment/computing/sku/{computing_unit.sku}", {"name": "renamed"}),
        ("post", f"equipment/{pk}/assignment", {"bench_id": bench.pk}),
        ("delete", f"equipment/{pk}/assignment", None),
        ("post", f"equipment/{pk}/actions/change-condition", {"condition": "out_of_service"}),
        ("post", f"equipment/computing/{pk}/actions/change-lifecycle", {"lifecycle_state": "retired"}),
    ]
    for method, path, body in writes:
        response = getattr(client, method)(ROOT + path, body, format="json")
        assert response.status_code == 403, (method, path, response.status_code)
    computing_unit.refresh_from_db()
    assert computing_unit.name == "Step0 PC" and computing_unit.deleted_at is None
    # Equipment is visible to coordinators and administrators only (owner decision R4).
    for path in ("equipment", f"equipment/computing/{pk}", "equipment/options?q=x", "equipment/facets", "equipment-kinds"):
        assert client.get(ROOT + path).status_code == 403, path
    # Organisation lookups stay readable (R9).
    assert client.get(ROOT + "departments").status_code == 200
    assert client.get(ROOT + "resource-groups").status_code == 200


@pytest.mark.django_db
def test_coordinator_can_create_and_delete_equipment(coordinator, computing_kind):
    client = _client(coordinator)
    created = client.post(
        ROOT + "equipment/computing", {"kind_id": computing_kind.pk, "sku": "S0-C-1", "name": "PC"}, format="json"
    )
    assert created.status_code == 201, created.data
    pk = ComputingEquipment.objects.get(sku="S0-C-1").pk
    assert client.delete(ROOT + f"equipment/computing/{pk}").status_code == 204


# D1 / OD12: catalog writes need the admin role ---------------------------------------------


@pytest.mark.django_db
def test_catalog_writes_are_admin_only(coordinator, lab_admin):
    coordinator.user_permissions.add(
        Permission.objects.get(content_type__app_label="labs", codename="add_equipmentcategory")
    )
    denied = _client(coordinator).post(
        ROOT + "equipment/reference-data/categories",
        {"name": "Optics", "key": "optics", "definition": "Optics"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="s0-coord",
    )
    assert denied.status_code == 403
    assert not EquipmentCategory.objects.filter(key="optics").exists()

    lab_admin.user_permissions.add(
        Permission.objects.get(content_type__app_label="labs", codename="add_equipmentcategory")
    )
    created = _client(lab_admin).post(
        ROOT + "equipment/reference-data/categories",
        {"name": "Optics", "key": "optics", "definition": "Optics"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="s0-admin",
    )
    assert created.status_code == 201, created.data


@pytest.mark.django_db
def test_equipment_lookup_references_are_admin_only(coordinator, lab_admin):
    """Lookups equipment points at by foreign key (owner decision 2026-11-10)."""
    permission = Permission.objects.get(content_type__app_label="labs", codename="add_department")
    coordinator.user_permissions.add(permission)
    lab_admin.user_permissions.add(permission)
    url = ROOT + "equipment/reference-data/departments"
    denied = _client(coordinator).post(url, {"name": "S0 dept"}, format="json", HTTP_IDEMPOTENCY_KEY="s0-d1")
    assert denied.status_code == 403
    created = _client(lab_admin).post(url, {"name": "S0 dept"}, format="json", HTTP_IDEMPOTENCY_KEY="s0-d2")
    assert created.status_code == 201, created.data


# D2: generic create builds the category subtype ------------------------------------------


@pytest.mark.django_db
def test_generic_create_builds_category_subtype_with_activity(coordinator, computing_kind):
    response = _client(coordinator).post(
        ROOT + "equipment", {"kind_id": computing_kind.pk, "sku": "S0-GEN-1", "name": "Generic PC"}, format="json"
    )
    assert response.status_code == 201, response.data
    unit = ComputingEquipment.objects.get(sku="S0-GEN-1")
    assert ComputingActivity.objects.filter(computing=unit).exists()
    listed = _client(coordinator).get(ROOT + "equipment/computing", {"search": "S0-GEN-1"})
    assert listed.status_code == 200
    assert [row["id"] for row in listed.data["data"]] == [unit.pk]


@pytest.mark.django_db
def test_generic_create_for_runtime_category_keeps_base_row(coordinator):
    category = EquipmentCategory.objects.create(name="Optics", key="optics", definition="Optics")
    kind = EquipmentKind.objects.create(category=category, name="Lens")
    response = _client(coordinator).post(
        ROOT + "equipment", {"kind_id": kind.pk, "sku": "S0-OPT-1", "name": "Lens"}, format="json"
    )
    assert response.status_code == 201, response.data
    unit = Equipment.objects.get(sku="S0-OPT-1")
    assert not ComputingEquipment.objects.filter(pk=unit.pk).exists()


# D3: create accepts every field its serializers accept -------------------------------------


@pytest.mark.django_db
def test_generic_create_accepts_declared_fields(coordinator, computing_kind):
    response = _client(coordinator).post(
        ROOT + "equipment",
        {
            "kind_id": computing_kind.pk,
            "sku": "S0-FIELDS-1",
            "name": "Fields",
            "firmware_version": "1.2.3",
            "power_draw_w": 45,
            "weight_kg": "2.25",
            "warranty_until": "2028-01-31",
            "calibration_required": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    unit = Equipment.objects.get(sku="S0-FIELDS-1")
    assert unit.firmware_version == "1.2.3"
    assert unit.power_draw_w == 45
    assert str(unit.weight_kg) == "2.25"
    assert unit.calibration_required is True
    assert response.data["data"]["placement"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["equipment", "equipment/computing"])
def test_create_rejects_removed_storage_room_field(coordinator, computing_kind, path):
    """``storage_room`` was removed; where a unit is kept is its placement."""
    room = Room.objects.create(sku=f"S0-ROOM-{path[-3:]}", name="Store")
    response = _client(coordinator).post(
        ROOT + path,
        {"kind_id": computing_kind.pk, "sku": f"S0-SR-{path[-3:]}", "name": "PC", "storage_room_id": room.pk},
        format="json",
    )
    assert response.status_code == 422, response.data
    assert not Equipment.objects.filter(sku=f"S0-SR-{path[-3:]}").exists()


# D4: delete refuses while live records point at the unit -----------------------------------


def _license():
    return License.objects.create(
        name="S0 licence",
        sku="S0-LIC-1",
        category=LicenseCategory.objects.create(name="S0 cat"),
        product=LicenseProduct.objects.create(name="S0 product"),
        vendor=LicenseVendor.objects.create(name="S0 vendor"),
        type=LicenseType.objects.create(name="S0 type"),
        identifier="S0-LIC",
    )


def _assert_delete_blocked(unit, blocker):
    with pytest.raises(EquipmentInUse) as error:
        delete_equipment(DeleteEquipmentInput(equipment_id=unit.pk, model=ComputingEquipment), actor=None)
    assert error.value.details == {"blockers": [blocker]}
    unit.refresh_from_db()
    assert unit.deleted_at is None


@pytest.mark.django_db
def test_delete_refused_with_active_bench_assignment(computing_unit):
    bench = Bench.objects.create(name="S0 bench", sku="S0-BENCH-2")
    EquipmentAssignment.objects.create(equipment=computing_unit, bench=bench, assigned_at=timezone.now())
    _assert_delete_blocked(computing_unit, "bench_assignment")


@pytest.mark.django_db
def test_delete_refused_with_active_license_seat(computing_unit):
    LicenseAssignment.objects.create(license=_license(), equipment=computing_unit)
    _assert_delete_blocked(computing_unit, "license_assignment")


@pytest.mark.django_db
def test_delete_refused_with_reserving_booking(computing_unit):
    start = timezone.now() + timedelta(days=1)
    EquipmentBooking.objects.create(
        equipment=computing_unit, booking_code="S0-BK-1", starts_at=start, ends_at=start + timedelta(hours=2)
    )
    _assert_delete_blocked(computing_unit, "booking")


@pytest.mark.django_db
def test_delete_allowed_after_dependents_are_released(computing_unit):
    bench = Bench.objects.create(name="S0 bench", sku="S0-BENCH-3")
    now = timezone.now()
    EquipmentAssignment.objects.create(equipment=computing_unit, bench=bench, assigned_at=now, unassigned_at=now)
    LicenseAssignment.objects.create(license=_license(), equipment=computing_unit, assigned_at=now, unassigned_at=now)
    start = timezone.now() + timedelta(days=1)
    EquipmentBooking.objects.create(
        equipment=computing_unit,
        booking_code="S0-BK-2",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        status="cancelled",
        cancellation_reason="no longer needed",
    )
    delete_equipment(DeleteEquipmentInput(equipment_id=computing_unit.pk, model=ComputingEquipment), actor=None)
    computing_unit.refresh_from_db()
    assert computing_unit.deleted_at is not None


@pytest.mark.django_db
def test_delete_api_returns_conflict_when_assigned(coordinator, computing_unit):
    bench = Bench.objects.create(name="S0 bench", sku="S0-BENCH-4")
    EquipmentAssignment.objects.create(equipment=computing_unit, bench=bench, assigned_at=timezone.now())
    response = _client(coordinator).delete(ROOT + f"equipment/computing/{computing_unit.pk}")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "equipment_in_use"


# D5: leaderboard counts each unit once, by its current state ------------------------------


@pytest.mark.django_db
def test_leaderboard_summary_counts_each_unit_once(computing_kind):
    broken = ComputingEquipment.objects.create(sku="S0-LB-1", name="A", kind=computing_kind)
    ComputingEquipment.objects.create(sku="S0-LB-2", name="B", kind=computing_kind)
    ComputingEquipment.objects.create(sku="S0-LB-3", name="C", kind=computing_kind, lifecycle_state="planned")
    deleted = ComputingEquipment.objects.create(sku="S0-LB-4", name="Gone", kind=computing_kind, lifecycle_state="lost")
    Equipment.objects.filter(pk=broken.pk).update(condition="out_of_service")
    Equipment.objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())

    summary = get_dashboard_summary()

    assert summary["total"] == 3
    assert summary["status"]["broken"] == 1
    assert summary["status"]["available"] == 1
    assert summary["status"]["on_order"] == 1
    assert summary["status"]["lost"] == 0
