"""Synthetic finance aggregation, access, calendar and compatibility regressions."""

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import resolve
from rest_framework.test import APIClient
from rest_framework_api_key.models import APIKey

from core.labs.features.analytics.api.finance.serializers import FinanceQuerySerializer
from core.labs.features.analytics.api.finance.views import (
    FinanceBreakdownAPIView,
    FinanceMonthlyTrendsAPIView,
    FinanceSummaryAPIView,
)
from core.labs.features.analytics.exceptions import AnalyticsValidationError
from core.labs.features.analytics.public import get_finance_breakdown, get_finance_monthly_trends, get_finance_summary
from core.labs.features.expense.public import aggregate_expense_cash_flow, get_financial_report
from core.labs.features.procurement.public import aggregate_procurement_cash_flow
from core.labs.models import (
    Expense,
    ExpensePayment,
    Purchase,
    PurchaseItem,
    PurchaseItemResource,
    PurchaseTransaction,
    Room,
)


@pytest.fixture()
def user(db):
    """Finance reports are for lab coordinators and admins: the default caller holds ``coord``."""
    from django.contrib.auth.models import Group

    from core.users.models import URSGroup
    from tests.factories import UserFactory

    caller = UserFactory(username="finance-coordinator")
    group = Group.objects.create(name="finance-coordinators")
    URSGroup.objects.create(group=group, urs_group_id=320001, labs_role="coord")
    caller.groups.add(group)
    return caller

PARAMS = {"currency": "EUR", "start_month": "2026-01", "end_month": "2026-03"}
WINDOW = {"currency": "EUR", "start_month": date(2026, 1, 1), "end_month": date(2026, 3, 1)}
BASE = "/api/labs/analytics/finance/"
ENDPOINTS = ["summary", "monthly-trends", "expense-type-breakdown"]


def _synthetic_expense(currency="EUR", expense_type="rent"):
    room = Room.objects.create(sku=f"SYNTH-{Room.objects.count()}", name="Synthetic room")
    return Expense.objects.create(
        resource_type=ContentType.objects.get_for_model(Room),
        resource_id=room.pk,
        name="Synthetic obligation",
        expense_type=expense_type,
        amount="999999.00",
        currency=currency,
        valid_from=date(2020, 1, 1),
        valid_until=date(2020, 2, 1),
    )


def _synthetic_payment(expense, amount, paid_at, kind="payment"):
    return ExpensePayment.objects.create(
        expense=expense, amount=amount, paid_at=paid_at, transaction_type=kind, reference="synthetic-shared"
    )


def _synthetic_purchase(currency="EUR"):
    return Purchase.objects.create(
        supplier="Synthetic supplier",
        purchase_date=date(2020, 1, 1),
        currency=currency,
        total_amount="999999.00",
        status="cancelled",
    )


def _synthetic_transaction(purchase, amount, settled_at, kind="payment"):
    return PurchaseTransaction.objects.create(
        purchase=purchase, amount=amount, settled_at=settled_at, transaction_type=kind, reference="synthetic-shared"
    )


@pytest.mark.django_db
def test_actuals_signed_net_sources_no_dedup_and_zero_fill(django_assert_num_queries):
    expense = _synthetic_expense()
    _synthetic_payment(expense, "0.10", date(2026, 1, 1))
    _synthetic_payment(expense, "0.20", date(2026, 1, 31))
    _synthetic_payment(expense, "1.00", date(2026, 3, 31), "refund")
    _synthetic_payment(expense, "700.00", date(2025, 12, 31))
    _synthetic_payment(expense, "800.00", date(2026, 4, 1))
    _synthetic_payment(_synthetic_expense("USD"), "900.00", date(2026, 1, 1))
    _synthetic_expense(expense_type="service")
    purchase = _synthetic_purchase()
    PurchaseItem.objects.create(purchase=purchase, description="Synthetic line A", unit_price="500.00")
    PurchaseItem.objects.create(purchase=purchase, description="Synthetic line B", unit_price="500.00")
    _synthetic_transaction(purchase, "0.30", datetime(2026, 1, 1, tzinfo=timezone.utc))
    _synthetic_transaction(purchase, "2.00", datetime(2026, 3, 31, tzinfo=timezone.utc), "refund")
    _synthetic_transaction(_synthetic_purchase("USD"), "999.00", datetime(2026, 1, 1, tzinfo=timezone.utc))
    with django_assert_num_queries(2):
        result = get_finance_monthly_trends(**WINDOW)
    assert result["combined"]["payments"] == {"amount": "0.60", "currency": "EUR"}
    assert result["combined"]["refunds"]["amount"] == "-3.00"
    assert result["combined"]["net"]["amount"] == "-2.40"
    assert result["combined"]["transaction_count"] == 5
    assert result["sources"]["expense"]["net"]["amount"] == "-0.70"
    assert result["sources"]["procurement"]["net"]["amount"] == "-1.70"
    assert [row["month"] for row in result["months"]] == ["2026-01", "2026-02", "2026-03"]
    assert result["months"][1]["combined"]["net"]["amount"] == "0.00"
    assert result["months"][1]["sources"]["expense"]["transaction_count"] == 0
    items = get_finance_breakdown(**WINDOW)["items"]
    assert [(item["source"], item["expense_type"]) for item in items] == [
        ("expense", "rent"),
        ("procurement", "procurement"),
    ]
    assert get_finance_summary(**WINDOW) == {key: value for key, value in result.items() if key != "months"}
    rows = aggregate_expense_cash_flow(currency="EUR", start_date=date(2026, 1, 1), end_date=date(2026, 4, 1))
    assert rows[0].amount.as_tuple().exponent == -2
    assert rows[0].transaction_count == 2


@pytest.mark.django_db
def test_timezone_half_open_boundaries_and_date_only_expenses():
    expense = _synthetic_expense()
    _synthetic_payment(expense, "10.00", date(2026, 3, 1))
    _synthetic_payment(expense, "90.00", date(2026, 4, 1))
    purchase = _synthetic_purchase()
    for instant, amount in [
        ("2026-02-28T22:59:59+00:00", "100.00"),
        ("2026-02-28T23:00:00+00:00", "1.00"),
        ("2026-03-31T21:59:59+00:00", "2.00"),
        ("2026-03-31T22:00:00+00:00", "200.00"),
    ]:
        _synthetic_transaction(purchase, amount, datetime.fromisoformat(instant))
    result = get_finance_monthly_trends(
        currency="EUR", start_month=date(2026, 3, 1), end_month=date(2026, 3, 1), timezone="Europe/Berlin"
    )
    assert result["combined"]["payments"]["amount"] == "13.00"
    assert result["period_start"] == datetime(2026, 2, 28, 23, tzinfo=timezone.utc)
    assert result["period_end"] == datetime(2026, 3, 31, 22, tzinfo=timezone.utc)
    rows = aggregate_procurement_cash_flow(
        currency="EUR",
        start_at=result["period_start"],
        end_at=result["period_end"],
        reporting_timezone=__import__("zoneinfo").ZoneInfo("Europe/Berlin"),
    )
    assert len(rows) == 1 and rows[0].month == date(2026, 3, 1) and rows[0].transaction_count == 2


@pytest.mark.django_db
def test_legacy_report_still_clamps_refund_net_and_filters_obligation_dates():
    expense = _synthetic_expense()
    _synthetic_payment(expense, "10.00", date(2026, 1, 1), "refund")
    before = get_financial_report()
    assert get_finance_summary(**WINDOW)["combined"]["net"]["amount"] == "-10.00"
    assert get_financial_report() == before
    assert get_financial_report(from_date=date(2026, 1, 1))["items"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_authenticated_and_api_key_access_and_anonymous_denial(endpoint, user):
    client = APIClient()
    denied = client.get(BASE + endpoint, PARAMS)
    assert denied.status_code in (401, 403)
    assert "data" not in denied.json()
    client.force_authenticate(user=user)
    response = client.get(BASE + endpoint, PARAMS)
    assert response.status_code == 200, response.content
    assert response.json()["data"]["combined"]["net"] == {"amount": "0.00", "currency": "EUR"}
    assert response["Cache-Control"] == "private, no-cache"
    client = APIClient()
    _, key = APIKey.objects.create_key(name="synthetic-finance")
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    assert client.get(BASE + endpoint, PARAMS).status_code == 200
    client.credentials(HTTP_AUTHORIZATION="Api-Key synthetic-invalid")
    assert client.get(BASE + endpoint, PARAMS).status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        {"currency": ""},
        {"currency": "eur"},
        {"currency": "EURO"},
        {"start_month": "2026-00"},
        {"start_month": "2026-01-01"},
        {"end_month": "2025-12"},
        {"end_month": "2028-01"},
        {"timezone": "Synthetic/Invalid"},
        {"end_month": "9999-12"},
        {"unknown": "1"},
    ],
)
@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_invalid_query_contract(endpoint, change, user):
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(BASE + endpoint, {**PARAMS, **change})
    assert response.status_code == 400, response.content
    assert response.json()["error"]["code"] == "invalid_query"
    assert "data" not in response.json()


@pytest.mark.django_db
def test_missing_and_repeated_parameters_and_24_month_boundary(user):
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get(BASE + "summary").status_code == 400
    assert (
        client.get(BASE + "summary?currency=EUR&currency=USD&start_month=2026-01&end_month=2026-03").status_code == 400
    )
    response = client.get(BASE + "monthly-trends", {**PARAMS, "end_month": "2027-12"})
    assert response.status_code == 200
    assert len(response.json()["data"]["months"]) == 24


def test_public_validation_precedes_foreign_queries():
    with patch("core.labs.features.analytics.queries.finance.aggregate_expense_cash_flow") as aggregate:
        with pytest.raises(AnalyticsValidationError):
            get_finance_summary(**{**WINDOW, "end_month": date(2028, 1, 1)})
        aggregate.assert_not_called()


def test_finance_route_resolves_to_capability_view():
    assert resolve(BASE + "summary").func.view_class is FinanceSummaryAPIView


def test_recursive_api_guards_and_finance_public_only_composition():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "api").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("core.labs.models"), path
                assert not (node.module or "").startswith("core.labs.features.expense"), path
                assert not (node.module or "").startswith("core.labs.features.procurement"), path
    tree = ast.parse((root / "queries" / "finance.py").read_text())
    foreign = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("core.labs.")
    }
    assert foreign == {"core.labs.features.expense.public", "core.labs.features.procurement.public"}


PARAMS = {"currency": "EUR", "start_month": "2026-01", "end_month": "2026-03"}
QUERY = {"currency": "EUR", "start_month": date(2026, 1, 1), "end_month": date(2026, 3, 1)}
ENDPOINTS = ["summary", "monthly-trends", "expense-type-breakdown"]


def _expense(*, currency="EUR", expense_type="rent"):
    room = Room.objects.create(sku=f"FIN-{Room.objects.count()}", name="Synthetic finance room")
    return Expense.objects.create(
        resource_type=ContentType.objects.get_for_model(Room),
        resource_id=room.pk,
        name="Synthetic obligation",
        amount=Decimal("999.00"),
        currency=currency,
        expense_type=expense_type,
        valid_from=date(2020, 1, 1),
        valid_until=date(2020, 12, 31),
    )


def _purchase(*, currency="EUR"):
    return Purchase.objects.create(
        supplier="Synthetic supplier",
        total_amount=Decimal("999.00"),
        currency=currency,
        status="cancelled",
        purchase_date=date(2020, 1, 1),
    )


def _payment(expense, amount, when, kind="payment"):
    return ExpensePayment.objects.create(expense=expense, amount=Decimal(amount), paid_at=when, transaction_type=kind)


def _transaction(purchase, amount, when, kind="payment"):
    return PurchaseTransaction.objects.create(
        purchase=purchase,
        amount=Decimal(amount),
        settled_at=when,
        transaction_type=kind,
        reference="shared-reference",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "eur"},
        {"currency": "EU"},
        {"currency": "€UR"},
        {"currency": ""},
        {"start_month": "2026-1"},
        {"start_month": "0000-01"},
        {"end_month": "2026-13"},
        {"end_month": "2025-12"},
        {"end_month": "2028-01"},
        {"timezone": "Not/AZone"},
        {"timezone": "../UTC"},
        {"start_month": "9999-11", "end_month": "9999-12"},
    ],
)
def test_query_validation(changes):
    serializer = FinanceQuerySerializer(data={**PARAMS, **changes})
    assert not serializer.is_valid()


def test_exact_24_months_and_default_timezone():
    serializer = FinanceQuerySerializer(data={**PARAMS, "end_month": "2027-12"})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["timezone"] == "UTC"


@pytest.mark.django_db
def test_empty_zero_filled_series_and_breakdown(django_assert_num_queries):
    with django_assert_num_queries(2):
        report = get_finance_monthly_trends(**QUERY)
    assert [item["month"] for item in report["months"]] == ["2026-01", "2026-02", "2026-03"]
    for month in report["months"]:
        for totals in [month["combined"], *month["sources"].values()]:
            assert totals["net"] == {"amount": "0.00", "currency": "EUR"}
            assert totals["transaction_count"] == 0
    assert get_finance_breakdown(**QUERY)["items"] == []


@pytest.mark.django_db
def test_exact_signed_refunds_currency_and_source_totals(django_assert_num_queries):
    expense = _expense()
    _payment(expense, "0.10", date(2026, 1, 1))
    _payment(expense, "0.20", date(2026, 1, 31))
    _payment(expense, "5.00", date(2026, 2, 1), "refund")
    purchase = _purchase()
    _transaction(purchase, "10.00", datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    _transaction(purchase, "20.00", datetime(2026, 3, 31, 23, 59, tzinfo=ZoneInfo("UTC")), "refund")
    _payment(_expense(currency="USD"), "100.00", date(2026, 1, 1))
    _transaction(_purchase(currency="USD"), "100.00", datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    with django_assert_num_queries(2):
        report = get_finance_summary(**QUERY)
    assert report["combined"] == {
        "payments": {"amount": "10.30", "currency": "EUR"},
        "refunds": {"amount": "-25.00", "currency": "EUR"},
        "net": {"amount": "-14.70", "currency": "EUR"},
        "transaction_count": 5,
    }
    assert report["sources"]["expense"]["net"]["amount"] == "-4.70"
    assert report["sources"]["procurement"]["net"]["amount"] == "-10.00"
    usd = get_finance_summary(**{**QUERY, "currency": "USD"})
    assert usd["combined"]["net"] == {"amount": "200.00", "currency": "USD"}
    items = get_finance_breakdown(**QUERY)["items"]
    assert [(item["source"], item["expense_type"]) for item in items] == [
        ("expense", "rent"),
        ("procurement", "procurement"),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("zone_name", ["UTC", "Europe/Berlin", "America/New_York"])
def test_timezone_half_open_boundaries_and_date_only_payments(zone_name):
    zone = ZoneInfo(zone_name)
    start = datetime(2026, 3, 1, tzinfo=zone)
    end = datetime(2026, 4, 1, tzinfo=zone)
    purchase = _purchase()
    for instant, amount in [
        (start - timedelta(microseconds=1), "100.00"),
        (start, "1.00"),
        (end - timedelta(microseconds=1), "2.00"),
        (end, "100.00"),
    ]:
        _transaction(purchase, amount, instant)
    expense = _expense()
    for day, amount in [
        (date(2026, 2, 28), "100.00"),
        (date(2026, 3, 1), "4.00"),
        (date(2026, 3, 31), "8.00"),
        (date(2026, 4, 1), "100.00"),
    ]:
        _payment(expense, amount, day)
    report = get_finance_monthly_trends(
        currency="EUR", start_month=date(2026, 3, 1), end_month=date(2026, 3, 1), timezone=zone_name
    )
    assert report["combined"]["net"]["amount"] == "15.00"
    assert report["combined"]["transaction_count"] == 4
    assert report["period_start"] == start
    assert report["period_end"] == end
    assert report["months"][0]["sources"]["procurement"]["net"]["amount"] == "3.00"


@pytest.mark.django_db
def test_purchase_items_allocations_do_not_multiply_cash_flow():
    purchase = _purchase()
    content_type = ContentType.objects.get_for_model(Room)
    for number in range(3):
        item = PurchaseItem.objects.create(
            purchase=purchase, description="Synthetic line", quantity=2, unit_price="5.00"
        )
        for offset in range(2):
            PurchaseItemResource.objects.create(
                purchase_item=item,
                resource_type=content_type,
                resource_id=100 + number * 2 + offset,
                acquisition_price="5.00",
            )
    instant = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    _transaction(purchase, "3.00", instant)
    _transaction(purchase, "3.00", instant)  # Same reference is deliberately not deduplicated.
    _payment(_expense(), "3.00", date(2026, 1, 1))
    report = get_finance_summary(**QUERY)
    assert report["combined"]["net"]["amount"] == "9.00"
    assert report["combined"]["transaction_count"] == 3


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("access", ["authenticated", "api_key", "anonymous"])
@pytest.mark.django_db
def test_finance_access_and_contract(api_client, user, endpoint, access):
    if access == "authenticated":
        api_client.force_authenticate(user=user)
    with patch("rest_framework_api_key.permissions.HasAPIKey.has_permission", return_value=access == "api_key"):
        response = api_client.get(f"/api/labs/analytics/finance/{endpoint}", PARAMS)
    if access == "anonymous":
        assert response.status_code in (401, 403)
        assert "data" not in response.data
    else:
        assert response.status_code == 200, response.content
        assert set(response.data) == {"data"}
        assert response.data["data"]["combined"]["net"] == {"amount": "0.00", "currency": "EUR"}
        assert response["Cache-Control"] == "private, no-cache"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "changes",
    [
        {"currency": None},
        {"start_month": None},
        {"end_month": None},
        {"unknown": "1"},
        {"page": "1"},
        {"end_month": "2028-01"},
    ],
)
@pytest.mark.django_db
def test_api_invalid_query(api_client, user, endpoint, changes):
    api_client.force_authenticate(user=user)
    params = {key: value for key, value in {**PARAMS, **changes}.items() if value is not None}
    with patch("rest_framework_api_key.permissions.HasAPIKey.has_permission", return_value=False):
        response = api_client.get(f"/api/labs/analytics/finance/{endpoint}", params)
    assert response.status_code == 400, response.content
    assert "error" in response.data and "data" not in response.data


@pytest.mark.django_db
def test_duplicate_query_rejected(api_client, user):
    api_client.force_authenticate(user=user)
    response = api_client.get(
        "/api/labs/analytics/finance/summary?currency=EUR&currency=USD&start_month=2026-01&end_month=2026-03"
    )
    assert response.status_code == 400


def test_recursive_finance_boundary():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "queries" / "finance").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            )
            for module in modules:
                assert not module.startswith("core.labs.models"), path
                for source in ("expense", "procurement"):
                    prefix = f"core.labs.features.{source}"
                    if module.startswith(prefix):
                        assert module == f"{prefix}.public", path


def test_finance_openapi_declares_required_inputs_and_money_schema():
    from django.urls import path
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.validation import validate_schema

    patterns = [
        path("finance/summary", FinanceSummaryAPIView.as_view()),
        path("finance/monthly-trends", FinanceMonthlyTrendsAPIView.as_view()),
        path("finance/expense-type-breakdown", FinanceBreakdownAPIView.as_view()),
    ]
    schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
    validate_schema(schema)
    for operation in schema["paths"].values():
        parameters = {parameter["name"]: parameter for parameter in operation["get"]["parameters"]}
        assert set(parameters) == {"currency", "start_month", "end_month", "timezone"}
        assert all(parameters[name]["required"] for name in ("currency", "start_month", "end_month"))
        assert set(operation["get"]["responses"]) >= {"200", "400"}
    money = schema["components"]["schemas"]["FinanceMoney"]["properties"]
    assert money["amount"]["type"] == "string"
    assert "pattern" in money["amount"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["", "user"])
@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_finance_requires_coordinator(endpoint, role):
    from django.contrib.auth.models import Group

    from core.users.models import URSGroup
    from tests.factories import UserFactory

    caller = UserFactory(username=f"finance-plain-{role or 'none'}")
    if role:
        group = Group.objects.create(name=f"finance-{role}")
        URSGroup.objects.create(group=group, urs_group_id=320100, labs_role=role)
        caller.groups.add(group)
    client = APIClient()
    client.force_authenticate(user=caller)
    response = client.get(BASE + endpoint, PARAMS)
    assert response.status_code == 403
    assert "data" not in response.json()
