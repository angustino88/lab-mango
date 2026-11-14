"""Tests for financial reporting queries and API endpoints."""
from __future__ import annotations

import itertools
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.expense import public
from core.labs.models import (
    Expense,
    ExpensePayment,
    ExpenseType,
    PaymentTransactionType,
    Room,
)
from core.users.models import User

_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"
_ROOM_SEQ = itertools.count(1)


def _make_room(name="Testing Room"):
    n = next(_ROOM_SEQ)
    return Room.objects.create(sku=f"RM-REP-{n:04d}", name=name)


@pytest.fixture
def room(db):
    return _make_room("Testing Room")


@pytest.fixture
def room2(db):
    return _make_room("Second Room")


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin_user",
        email="admin@example.com",
        password="secret",
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
class TestFinancialReportQueries:
    def test_empty_financial_report(self):
        report = public.get_financial_report(currency="EUR")
        assert report["currency"] == "EUR"
        assert report["summary"]["total_budgeted"] == Decimal("0.00")
        assert report["summary"]["total_paid"] == Decimal("0.00")
        assert report["summary"]["total_pending"] == Decimal("0.00")
        assert report["summary"]["expense_count"] == 0
        assert report["items"] == []

    def test_payment_status_derivation_and_kpis(self, room):
        today = timezone.now().date()

        # 1. Fully paid expense
        e1 = Expense.objects.create(
            name="Rent",
            expense_type=ExpenseType.RENT,
            amount=Decimal("1000.00"),
            currency="EUR",
            valid_from=today - timedelta(days=30),
            valid_until=today + timedelta(days=30),
            resource=room,
        )
        ExpensePayment.objects.create(
            expense=e1,
            amount=Decimal("1000.00"),
            transaction_type=PaymentTransactionType.PAYMENT,
            paid_at=today - timedelta(days=15),
        )

        # 2. Partially paid expense
        e2 = Expense.objects.create(
            name="Electricity",
            expense_type=ExpenseType.UTILITIES,
            amount=Decimal("500.00"),
            currency="EUR",
            valid_from=today - timedelta(days=20),
            valid_until=today + timedelta(days=10),
            resource=room,
        )
        ExpensePayment.objects.create(
            expense=e2,
            amount=Decimal("200.00"),
            transaction_type=PaymentTransactionType.PAYMENT,
            paid_at=today - timedelta(days=5),
        )

        # 3. Unpaid expense (not overdue)
        Expense.objects.create(
            name="Cleaning",
            expense_type=ExpenseType.MAINTENANCE,
            amount=Decimal("300.00"),
            currency="EUR",
            valid_from=today,
            valid_until=today + timedelta(days=15),
            resource=room,
        )

        # 4. Overdue expense (valid_until in past, no payment)
        Expense.objects.create(
            name="Hardware Repair",
            expense_type=ExpenseType.SERVICE,
            amount=Decimal("400.00"),
            currency="EUR",
            valid_from=today - timedelta(days=60),
            valid_until=today - timedelta(days=5),
            resource=room,
        )

        # 5. Expense with payment and refund
        e5 = Expense.objects.create(
            name="Software License",
            expense_type=ExpenseType.OTHER,
            amount=Decimal("600.00"),
            currency="EUR",
            valid_from=today - timedelta(days=10),
            valid_until=today + timedelta(days=20),
            resource=room,
        )
        ExpensePayment.objects.create(
            expense=e5,
            amount=Decimal("300.00"),
            transaction_type=PaymentTransactionType.PAYMENT,
            paid_at=today - timedelta(days=8),
        )
        ExpensePayment.objects.create(
            expense=e5,
            amount=Decimal("50.00"),
            transaction_type=PaymentTransactionType.REFUND,
            paid_at=today - timedelta(days=2),
        )

        report = public.get_financial_report(currency="EUR")
        summary = report["summary"]

        assert summary["total_budgeted"] == Decimal("2800.00")
        assert summary["total_paid"] == Decimal("1450.00")  # 1000 + 200 + (300 - 50)
        assert summary["total_pending"] == Decimal("1350.00")  # 0 + 300 + 300 + 400 + 350
        assert summary["total_refunded"] == Decimal("50.00")
        assert summary["expense_count"] == 5

        statuses = {item["name"]: item["payment_status"] for item in report["items"]}
        assert statuses["Rent"] == "paid"
        assert statuses["Electricity"] == "partially_paid"
        assert statuses["Cleaning"] == "unpaid"
        assert statuses["Hardware Repair"] == "overdue"
        assert statuses["Software License"] == "partially_paid"

    def test_filter_by_room_and_status(self, room, room2):
        today = timezone.now().date()
        Expense.objects.create(
            name="Room 1 Expense",
            expense_type=ExpenseType.RENT,
            amount=Decimal("100.00"),
            currency="EUR",
            valid_from=today,
            resource=room,
        )
        Expense.objects.create(
            name="Room 2 Expense",
            expense_type=ExpenseType.RENT,
            amount=Decimal("200.00"),
            currency="EUR",
            valid_from=today,
            resource=room2,
        )

        r1_report = public.get_financial_report(room_id=room.id)
        assert r1_report["summary"]["expense_count"] == 1
        assert r1_report["items"][0]["name"] == "Room 1 Expense"

        unpaid_report = public.get_financial_report(status="unpaid")
        assert unpaid_report["summary"]["expense_count"] == 2


@pytest.mark.django_db
class TestFinancialReportAPI:
    def test_expenses_report_endpoint(self, admin_client, room):
        today = timezone.now().date()
        Expense.objects.create(
            name="Office Supplies",
            expense_type=ExpenseType.OTHER,
            amount=Decimal("150.00"),
            currency="EUR",
            valid_from=today,
            resource=room,
        )
        response = admin_client.get("/api/labs/expenses/report")
        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload
        assert payload["data"]["summary"]["budgeted"] == {"amount": "150.00", "currency": "EUR"}
        assert len(payload["data"]["items"]) == 1

    def test_financial_report_canonical_alias(self, admin_client, room):
        response = admin_client.get("/api/labs/financial-report")
        assert response.status_code == 200

    def test_room_expenses_report_endpoint(self, admin_client, room):
        response = admin_client.get(f"/api/labs/rooms/{room.id}/expenses/report")
        assert response.status_code == 200

    def test_room_not_found_returns_404(self, admin_client):
        response = admin_client.get("/api/labs/rooms/99999/expenses/report")
        assert response.status_code == 404

    def test_unauthenticated_without_api_key_rejected(self, room):
        client = APIClient()
        with patch(_PATCH_APIKEY, return_value=False):
            response = client.get("/api/labs/financial-report")
            assert response.status_code in (401, 403)
