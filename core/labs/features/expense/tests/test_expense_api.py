"""Expense API behaviour: room-scoped expenses and payments, admin-only writes."""

import itertools
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group

from core.labs.models import Expense, ExpensePayment, Room
from core.users.models import URSGroup

pytestmark = pytest.mark.django_db

_ROOM_SEQUENCE = itertools.count(1)
_URS_SEQUENCE = itertools.count(1)
_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"


def _admin_client(api_client, user):
    group, _ = Group.objects.get_or_create(name="lab-admin")
    URSGroup.objects.create(
        group=group,
        urs_group_id=next(_URS_SEQUENCE),
        labs_role="admin",
    )
    user.groups.add(group)
    api_client.force_authenticate(user=user)
    return api_client


def _room():
    number = next(_ROOM_SEQUENCE)
    return Room.objects.create(sku=f"RM-EXP-{number:03d}", name=f"Expense Room {number}")


class TestRoomExpenses:
    def test_admin_creates_expense_for_room(self, api_client, user):
        client = _admin_client(api_client, user)
        room = _room()
        response = client.post(
            f"/api/labs/rooms/{room.pk}/expenses",
            {
                "name": "Rent",
                "expense_type": "rent",
                "cost": {"amount": "1200.00", "currency": "EUR"},
                "billing_period": "monthly",
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        assert Expense.objects.filter(resource_id=room.pk, name="Rent").exists()

    def test_non_admin_cannot_create_expense(self, api_client, user):
        user = user
        api_client.force_authenticate(user=user)
        room = _room()
        response = api_client.post(
            f"/api/labs/rooms/{room.pk}/expenses",
            {
                "name": "Rent",
                "expense_type": "rent",
                "cost": {"amount": "10.00", "currency": "EUR"},
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert response.status_code == 403
        assert not Expense.objects.filter(resource_id=room.pk).exists()

    def test_missing_room_returns_404(self, api_client, user):
        client = _admin_client(api_client, user)
        response = client.get("/api/labs/rooms/999999/expenses")
        assert response.status_code == 404

    def test_invalid_period_is_rejected(self, api_client, user):
        client = _admin_client(api_client, user)
        room = _room()
        response = client.post(
            f"/api/labs/rooms/{room.pk}/expenses",
            {
                "name": "Rent",
                "expense_type": "rent",
                "cost": {"amount": "10.00", "currency": "EUR"},
                "start_date": "2026-06-01",
                "end_date": "2026-01-01",
            },
            format="json",
        )
        assert response.status_code == 422
        assert not Expense.objects.filter(resource_id=room.pk).exists()


class TestExpensePayments:
    def test_admin_records_payment(self, api_client, user):
        client = _admin_client(api_client, user)
        room = _room()
        expense = Expense.objects.create(
            resource_type_id=_room_content_type_id(),
            resource_id=room.pk,
            name="Service",
            expense_type="service",
            amount=Decimal("500.00"),
            valid_from=date(2026, 1, 1),
        )
        response = client.post(
            f"/api/labs/expenses/{expense.pk}/payments",
            {
                "transaction_type": "payment",
                "total": {"amount": "250.00", "currency": "EUR"},
                "paid_date": "2026-02-01",
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        assert ExpensePayment.objects.filter(expense=expense, amount=Decimal("250.00")).exists()
        assert response.json()["data"]["total"] == {"amount": "250.00", "currency": "EUR"}

        other_currency = client.post(
            f"/api/labs/expenses/{expense.pk}/payments",
            {"transaction_type": "payment", "total": {"amount": "1.00", "currency": "USD"}, "paid_date": "2026-02-02"},
            format="json",
        )
        assert other_currency.status_code == 422, other_currency.content  # FMT-2: the expense's currency only
        assert ExpensePayment.objects.filter(expense=expense).count() == 1

    def test_non_positive_payment_rejected(self, api_client, user):
        client = _admin_client(api_client, user)
        room = _room()
        expense = Expense.objects.create(
            resource_type_id=_room_content_type_id(),
            resource_id=room.pk,
            name="Service",
            expense_type="service",
            amount=Decimal("500.00"),
            valid_from=date(2026, 1, 1),
        )
        response = client.post(
            f"/api/labs/expenses/{expense.pk}/payments",
            {"transaction_type": "payment", "total": {"amount": "0.00", "currency": "EUR"}, "paid_date": "2026-02-01"},
            format="json",
        )
        assert response.status_code in (400, 422)
        assert not ExpensePayment.objects.filter(expense=expense).exists()


def _room_content_type_id():
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(Room).pk


def _coord_client(api_client, user):
    group, _ = Group.objects.get_or_create(name="lab-coord")
    URSGroup.objects.create(
        group=group,
        urs_group_id=next(_URS_SEQUENCE),
        labs_role="coord",
    )
    user.groups.add(group)
    api_client.force_authenticate(user=user)
    return api_client


class TestExpenseAccess:
    def test_coordinator_can_read_room_expenses(self, api_client, user):
        client = _coord_client(api_client, user)
        room = _room()
        response = client.get(f"/api/labs/rooms/{room.pk}/expenses")
        assert response.status_code == 200, response.content

    def test_coordinator_can_create_expense(self, api_client, user):
        client = _coord_client(api_client, user)
        room = _room()
        response = client.post(
            f"/api/labs/rooms/{room.pk}/expenses",
            {
                "name": "Rent",
                "expense_type": "rent",
                "cost": {"amount": "10.00", "currency": "EUR"},
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        assert Expense.objects.filter(resource_id=room.pk, name="Rent").exists()

    def test_plain_user_cannot_create_expense(self, api_client, user):
        api_client.force_authenticate(user=user)
        room = _room()
        response = api_client.post(
            f"/api/labs/rooms/{room.pk}/expenses",
            {
                "name": "Rent",
                "expense_type": "rent",
                "cost": {"amount": "10.00", "currency": "EUR"},
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert response.status_code == 403
        assert not Expense.objects.filter(resource_id=room.pk).exists()

    def test_api_key_can_read_room_expenses(self, api_client):
        room = _room()
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.get(f"/api/labs/rooms/{room.pk}/expenses")
        assert response.status_code == 200, response.content

    def test_api_key_cannot_create_expense_by_default(self, api_client):
        """API keys are read-only unless API_KEY_WRITE_ACCESS_ENABLED (owner decision D4)."""
        room = _room()
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                f"/api/labs/rooms/{room.pk}/expenses",
                {"name": "Rent", "expense_type": "rent", "cost": {"amount": "10.00", "currency": "EUR"}},
                format="json",
            )
        assert response.status_code == 401
        assert not Expense.objects.filter(resource_id=room.pk).exists()

    def test_api_key_can_create_expense_when_writes_are_enabled(self, settings, api_client):
        settings.API_KEY_WRITE_ACCESS_ENABLED = True
        room = _room()
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                f"/api/labs/rooms/{room.pk}/expenses",
                {
                    "name": "Rent",
                    "expense_type": "rent",
                    "cost": {"amount": "10.00", "currency": "EUR"},
                    "start_date": "2026-01-01",
                },
                format="json",
            )
        assert response.status_code == 201, response.content
        assert Expense.objects.filter(resource_id=room.pk, name="Rent").exists()

    def test_anonymous_without_api_key_is_rejected(self, api_client):
        room = _room()
        with patch(_PATCH_APIKEY, return_value=False):
            response = api_client.get(f"/api/labs/rooms/{room.pk}/expenses")
        assert response.status_code in (401, 403)


def _make_license():
    from core.labs.models import License
    from core.labs.models.resource.license.license import (
        LicenseCategory,
        LicenseProduct,
        LicenseType,
        LicenseVendor,
    )

    n = next(_ROOM_SEQUENCE)
    vendor = LicenseVendor.objects.create(name=f"Vendor {n}")
    product = LicenseProduct.objects.create(name=f"CANoe {n}", vendor=vendor)
    lic_type = LicenseType.objects.create(name=f"Floating {n}")
    category = LicenseCategory.objects.create(name=f"Sim {n}")
    return License.objects.create(
        sku=f"LIC-EXP-{n:03d}",
        name=f"CANoe License {n}",
        vendor=vendor,
        product=product,
        type=lic_type,
        category=category,
    )


def _make_equipment():
    from core.labs.models import Equipment, EquipmentCategory, EquipmentKind

    n = next(_ROOM_SEQUENCE)
    category, _ = EquipmentCategory.objects.get_or_create(
        key="instrument",
        defaults={"name": "Instrument", "definition": "Measurement instruments"},
    )
    kind = EquipmentKind.objects.create(name=f"Scope Kind {n}", category=category)
    return Equipment.objects.create(sku=f"EQ-EXP-{n:03d}", name=f"Oscilloscope {n}", kind=kind)


class TestMultiResourceExpenses:
    def test_create_list_and_pay_license_fee_expense(self, api_client, user):
        client = _admin_client(api_client, user)
        lic = _make_license()
        equipment = _make_equipment()
        room = _room()

        lic_resp = client.post(
            "/api/labs/expenses",
            {
                "resource_kind": "license",
                "resource_id": lic.pk,
                "name": "Annual CANoe Renewal",
                "expense_type": "license_fee",
                "cost": {"amount": "4200.00", "currency": "EUR"},
                "billing_period": "annual",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "supplier": "Vector",
            },
            format="json",
        )
        assert lic_resp.status_code == 201, lic_resp.content
        created = lic_resp.json()["data"]
        assert created["resource_kind"] == {"value": "license", "label": "License"}
        assert created["resource"] == {"id": lic.pk, "name": lic.name}
        assert created["room"] is None
        assert created["expense_type"] == {"value": "license_fee", "label": "License fee"}

        # Record a payment against the license expense
        pay_resp = client.post(
            f"/api/labs/expenses/{created['id']}/payments",
            {
                "transaction_type": "payment",
                "total": {"amount": "4200.00", "currency": "EUR"},
                "paid_date": "2026-01-15",
                "reference": "INV-2026-01",
            },
            format="json",
        )
        assert pay_resp.status_code == 201, pay_resp.content

        # Also create an equipment calibration expense and a room rent expense
        eq_resp = client.post(
            "/api/labs/expenses",
            {
                "resource_kind": "equipment",
                "resource_id": equipment.pk,
                "name": "Annual Calibration",
                "expense_type": "calibration",
                "cost": {"amount": "650.00", "currency": "EUR"},
                "billing_period": "annual",
                "start_date": "2026-02-01",
            },
            format="json",
        )
        assert eq_resp.status_code == 201, eq_resp.content

        room_resp = client.post(
            "/api/labs/expenses",
            {
                "resource_kind": "room",
                "resource_id": room.pk,
                "name": "Lab Rent",
                "expense_type": "rent",
                "cost": {"amount": "1500.00", "currency": "EUR"},
                "billing_period": "monthly",
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert room_resp.status_code == 201, room_resp.content
        assert room_resp.json()["data"]["room"] == {"id": room.pk, "name": room.name}

        # List all and filter by resource_kind / resource_id / expense_type
        all_resp = client.get("/api/labs/expenses")
        assert all_resp.status_code == 200
        assert len(all_resp.json()["data"]) == 3

        lic_list = client.get("/api/labs/expenses", {"resource_kind": "license", "resource_id": lic.pk})
        assert lic_list.status_code == 200
        assert [row["name"] for row in lic_list.json()["data"]] == ["Annual CANoe Renewal"]

        eq_list = client.get("/api/labs/expenses", {"expense_type": "calibration"})
        assert eq_list.status_code == 200
        assert [row["name"] for row in eq_list.json()["data"]] == ["Annual Calibration"]

    def test_soft_deleted_or_missing_resource_returns_404(self, api_client, user):
        from django.utils import timezone

        client = _admin_client(api_client, user)
        lic = _make_license()
        lic.deleted_at = timezone.now()
        lic.save(update_fields=["deleted_at"])

        deleted_resp = client.post(
            "/api/labs/expenses",
            {
                "resource_kind": "license",
                "resource_id": lic.pk,
                "name": "Should fail",
                "expense_type": "license_fee",
                "cost": {"amount": "100.00", "currency": "EUR"},
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert deleted_resp.status_code == 404

        missing_resp = client.get("/api/labs/expenses", {"resource_kind": "license", "resource_id": 999999})
        assert missing_resp.status_code == 404

    def test_resource_id_without_resource_kind_returns_400(self, api_client, user):
        client = _admin_client(api_client, user)
        resp = client.get("/api/labs/expenses", {"resource_id": 1})
        assert resp.status_code == 400

    def test_plain_user_cannot_create_multi_resource_expense(self, api_client, user):
        api_client.force_authenticate(user=user)
        lic = _make_license()
        resp = api_client.post(
            "/api/labs/expenses",
            {
                "resource_kind": "license",
                "resource_id": lic.pk,
                "name": "Unauthorized",
                "expense_type": "license_fee",
                "cost": {"amount": "10.00", "currency": "EUR"},
                "start_date": "2026-01-01",
            },
            format="json",
        )
        assert resp.status_code == 403
