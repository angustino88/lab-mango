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

    def test_api_key_can_create_expense(self, api_client):
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
