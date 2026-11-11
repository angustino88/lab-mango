"""Focused failure, HTTP schema and modular compatibility regressions."""

from datetime import date
from unittest.mock import patch

import pytest
from django.urls import include, path, resolve
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema
from jsonschema import Draft4Validator

from core.labs.features.analytics.api.distribution.views import (
    BenchGroupSummaryAPIView,
    DeprecatedLabGroupSummaryAPIView,
    EquipmentStatusSummaryAPIView,
)
from core.labs.features.analytics.api.insights.views import (
    BookedVsUsedAPIView,
    DashboardSummaryAPIView,
    EquipmentAvailabilityAPIView,
)
from core.labs.features.analytics.api.observations.views import (
    BookingCountAPIView,
    LabCountAPIView,
    LabVisitsAPIView,
    UserCountAPIView,
)
from core.labs.features.analytics.api.storage.views import StorageQuotaAPIView
from core.labs.features.analytics.api.utilization.views import (
    LabEfficiencyAPIView,
    LabUsageTimeframeAPIView,
    ProjectUsageAPIView,
    UserBookingEfficiencyAPIView,
    UserLabUsageAPIView,
)
from core.labs.features.analytics.public import get_finance_summary


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

BASE = "/api/labs/analytics/finance/"
PARAMS = {"currency": "EUR", "start_month": "2026-01", "end_month": "2026-03"}
WINDOW = {"currency": "EUR", "start_month": date(2026, 1, 1), "end_month": date(2026, 3, 1)}
ENDPOINTS = ("summary", "monthly-trends", "expense-type-breakdown")


@pytest.mark.parametrize("source", ["expense", "procurement"])
def test_source_failure_is_not_reported_as_zero_cash_flow(source: str) -> None:
    prefix = "core.labs.features.analytics.queries.finance"
    with (
        patch(f"{prefix}.aggregate_expense_cash_flow", return_value=()),
        patch(f"{prefix}.aggregate_procurement_cash_flow", return_value=()),
        patch(f"{prefix}.aggregate_{source}_cash_flow", side_effect=RuntimeError("Synthetic source failure")),
    ):
        with pytest.raises(RuntimeError, match="Synthetic source failure"):
            get_finance_summary(**WINDOW)


def test_analytics_routes_resolve_to_capability_views() -> None:
    routes = [
        ("bench-group", BenchGroupSummaryAPIView, "analytics-bench-group"),
        ("lab-group", DeprecatedLabGroupSummaryAPIView, "analytics-lab-group"),
        ("lab-equipment-status", EquipmentStatusSummaryAPIView, "analytics-equipment-status"),
        ("lab-efficiency", LabEfficiencyAPIView, "analytics-lab-efficiency"),
        ("project-usage", ProjectUsageAPIView, "analytics-project-usage"),
        ("user-lab-usage", UserLabUsageAPIView, "analytics-user-lab-usage"),
        ("user-booking-efficiency", UserBookingEfficiencyAPIView, "analytics-user-booking-efficiency"),
        ("lab-usage-by-timeframe", LabUsageTimeframeAPIView, "analytics-lab-usage-timeframe"),
        ("storage-quota", StorageQuotaAPIView, "analytics-storage-quota"),
        ("lab-visits", LabVisitsAPIView, "analytics-lab-visits"),
        ("booking", BookingCountAPIView, "analytics-booking-count"),
        ("lab-count", LabCountAPIView, "analytics-lab-count"),
        ("user-count", UserCountAPIView, "analytics-user-count"),
        ("dashboard-summary", DashboardSummaryAPIView, "analytics-dashboard-summary"),
        ("booked-vs-used", BookedVsUsedAPIView, "analytics-booked-vs-used"),
        ("equipment-availability", EquipmentAvailabilityAPIView, "analytics-equipment-availability"),
    ]
    for route, view_class, url_name in routes:
        match = resolve("/api/labs/analytics/" + route)
        assert match.url_name == url_name
        assert match.func.view_class is view_class


@pytest.fixture(scope="module")
def finance_schema() -> dict:
    schema = SchemaGenerator(
        patterns=[path("api/labs/analytics/", include("core.labs.features.analytics.api.urls"))]
    ).get_schema(request=None, public=True)
    validate_schema(schema)
    return schema


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("valid_query", [True, False])
def test_runtime_response_matches_openapi(
    api_client, user, finance_schema: dict, endpoint: str, valid_query: bool
) -> None:
    api_client.force_authenticate(user=user)
    response = api_client.get(BASE + endpoint, PARAMS if valid_query else {**PARAMS, "unknown": "1"})
    assert response.status_code == (200 if valid_query else 400)
    operation = finance_schema["paths"][BASE + endpoint]["get"]
    response_schema = operation["responses"][str(response.status_code)]["content"]["application/json"]["schema"]
    Draft4Validator({**response_schema, "components": finance_schema["components"]}).validate(response.json())
    if not valid_query:
        error = response.json()["error"]
        assert set(error) == {"code", "message", "details", "request_id"}
        assert error["code"] == "invalid_query"
        assert error["details"]
        assert error["request_id"] == response["X-Request-ID"]
