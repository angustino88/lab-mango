"""Database-free finance HTTP boundary, UTC, security and throttle regressions."""

from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.urls import include, path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema
from jsonschema import Draft4Validator
from rest_framework.test import APIClient

from core.labs.features.analytics.api.finance.throttles import FinanceCallerThrottle
from core.labs.features.analytics.exceptions import AnalyticsValidationError
from core.labs.features.analytics.public import get_finance_breakdown, get_finance_monthly_trends, get_finance_summary

BASE = "/api/labs/analytics/finance/"
ENDPOINTS = ("summary", "monthly-trends", "expense-type-breakdown")
PARAMS = {"currency": "EUR", "start_month": "2026-01", "end_month": "2026-03"}
SOURCE = "core.labs.features.analytics.queries.finance"
PUBLIC_QUERIES = (get_finance_summary, get_finance_monthly_trends, get_finance_breakdown)


@pytest.fixture(scope="module")
def finance_schema() -> dict:
    schema = SchemaGenerator(
        patterns=[path("api/labs/analytics/", include("core.labs.features.analytics.api.urls"))]
    ).get_schema(request=None, public=True)
    validate_schema(schema)
    return schema


@pytest.fixture(autouse=True)
def isolated_finance_throttle():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def caller() -> APIClient:
    # Superuser holds every Labs role without a database query (finance needs ``coord``).
    client = APIClient()
    client.force_authenticate(user=get_user_model()(pk=10001, username="synthetic-finance-caller", is_superuser=True))
    return client


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_http_timestamps_are_utc_under_active_non_utc_zone(caller, endpoint):
    with (
        timezone.override("Asia/Tokyo"),
        patch(f"{SOURCE}.aggregate_expense_cash_flow", return_value=()),
        patch(f"{SOURCE}.aggregate_procurement_cash_flow", return_value=()),
    ):
        response = caller.get(BASE + endpoint, {**PARAMS, "timezone": "Europe/Berlin"})
    assert response.status_code == 200
    assert response.json()["data"]["period_start"] == "2025-12-31T23:00:00Z"
    assert response.json()["data"]["period_end"] == "2026-03-31T22:00:00Z"


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "Etc/GMT-14"])
@pytest.mark.parametrize("query", PUBLIC_QUERIES)
def test_public_extreme_boundary_rejects_before_sources(query, zone):
    with (
        patch(f"{SOURCE}.aggregate_expense_cash_flow") as expense,
        patch(f"{SOURCE}.aggregate_procurement_cash_flow") as procurement,
    ):
        with pytest.raises(AnalyticsValidationError, match="boundaries must be representable"):
            query(currency="EUR", start_month=date(1, 1, 1), end_month=date(1, 1, 1), timezone=zone)
    expense.assert_not_called()
    procurement.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("zone", ["Asia/Tokyo", "Etc/GMT-14"])
def test_http_extreme_boundary_is_invalid_query_without_sources(caller, endpoint, zone):
    with (
        patch(f"{SOURCE}.aggregate_expense_cash_flow") as expense,
        patch(f"{SOURCE}.aggregate_procurement_cash_flow") as procurement,
    ):
        response = caller.get(
            BASE + endpoint,
            {"currency": "EUR", "start_month": "0001-01", "end_month": "0001-01", "timezone": zone},
        )
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == "invalid_query"
    assert error["details"]
    assert error["request_id"] == response["X-Request-ID"]
    expense.assert_not_called()
    procurement.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_schema_api_key_alternative_required_queries_and_errors(finance_schema, endpoint):
    operation = finance_schema["paths"][BASE + endpoint]["get"]
    assert {"financeApiKey": []} in operation["security"]
    assert {} not in operation["security"]
    scheme = finance_schema["components"]["securitySchemes"]["financeApiKey"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "Authorization"
    assert "Api-Key" in scheme["description"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"currency", "start_month", "end_month", "timezone"}
    assert all(parameters[name]["required"] for name in ("currency", "start_month", "end_month"))
    assert set(operation["responses"]) >= {"200", "400", "401", "403", "429"}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("access", ["user", "api_key"])
def test_shared_throttle_returns_standard_429_before_sources(caller, finance_schema, endpoint, access):
    if access == "api_key":
        caller.force_authenticate(user=AnonymousUser())
    with (
        patch.object(FinanceCallerThrottle, "rate", "2/min"),
        patch("rest_framework_api_key.permissions.HasAPIKey.has_permission", return_value=access == "api_key"),
        patch(f"{SOURCE}.aggregate_expense_cash_flow", return_value=()) as expense,
        patch(f"{SOURCE}.aggregate_procurement_cash_flow", return_value=()) as procurement,
    ):
        assert caller.get(BASE + "summary", PARAMS).status_code == 200
        assert caller.get(BASE + "monthly-trends", PARAMS).status_code == 200
        expense.reset_mock()
        procurement.reset_mock()
        response = caller.get(BASE + endpoint, PARAMS)
        expense.assert_not_called()
        procurement.assert_not_called()
        if access == "user":
            caller.force_authenticate(user=get_user_model()(pk=10002, username="synthetic-finance-other", is_superuser=True))
            other = caller.get(BASE + endpoint, PARAMS)
        else:
            other = caller.get(BASE + endpoint, PARAMS, REMOTE_ADDR="192.0.2.2")
        assert other.status_code == 200
    assert response.status_code == 429
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == "rate_limited"
    assert error["request_id"] == response["X-Request-ID"]
    assert 0 < int(response["Retry-After"]) <= 60
    response_schema = finance_schema["paths"][BASE + endpoint]["get"]["responses"]["429"]["content"][
        "application/json"
    ]["schema"]
    Draft4Validator({**response_schema, "components": finance_schema["components"]}).validate(response.json())


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_database_free_runtime_matches_schema(caller, finance_schema, endpoint):
    with (
        patch(f"{SOURCE}.aggregate_expense_cash_flow", return_value=()),
        patch(f"{SOURCE}.aggregate_procurement_cash_flow", return_value=()),
    ):
        for params, expected_status in ((PARAMS, 200), ({**PARAMS, "unknown": "1"}, 400)):
            response = caller.get(BASE + endpoint, params)
            assert response.status_code == expected_status
            response_schema = finance_schema["paths"][BASE + endpoint]["get"]["responses"][str(expected_status)][
                "content"
            ]["application/json"]["schema"]
            Draft4Validator({**response_schema, "components": finance_schema["components"]}).validate(response.json())


def test_forwarded_ip_cannot_bypass_api_key_budget(caller):
    caller.force_authenticate(user=AnonymousUser())
    with (
        patch.object(FinanceCallerThrottle, "rate", "1/min"),
        patch("rest_framework_api_key.permissions.HasAPIKey.has_permission", return_value=True),
        patch(f"{SOURCE}.aggregate_expense_cash_flow", return_value=()) as expense,
        patch(f"{SOURCE}.aggregate_procurement_cash_flow", return_value=()) as procurement,
    ):
        assert caller.get(BASE + "summary", PARAMS, HTTP_X_FORWARDED_FOR="192.0.2.1").status_code == 200
        expense.reset_mock()
        procurement.reset_mock()
        assert caller.get(BASE + "summary", PARAMS, HTTP_X_FORWARDED_FOR="192.0.2.2").status_code == 429
        expense.assert_not_called()
        procurement.assert_not_called()
