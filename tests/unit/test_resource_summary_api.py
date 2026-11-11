"""Independent summary contracts and HTTP behavior without database access."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from core.common.queries.status_summary import status_summary

STATUS_ENDPOINTS = [
    ("equipment/status-summary", "equipment", "get_equipment_status_summary"),
    ("equipment/computing/activity-summary", "equipment", "get_computing_activity_summary"),
    ("licenses/status-summary", "licenses", "get_license_status_summary"),
    ("benches/status-summary", "benches", "get_bench_status_summary"),
    ("rooms/status-summary", "locations.rooms", "get_room_status_summary"),
    ("stations/status-summary", "locations.stations", "get_station_status_summary"),
]


@pytest.fixture()
def summary_contract_settings(settings):
    """Exercise intended contract middleware/handler absent from default test settings."""
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, "core.common.api.correlation.RequestCorrelationMiddleware"]
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "EXCEPTION_HANDLER": "core.common.api.exceptions.api_exception_handler",
    }


@pytest.fixture()
def summary_client(summary_contract_settings):
    client = APIClient()
    # Superuser stub: equipment reads are role-checked (coordinators only); no database needed.
    client.force_authenticate(user=SimpleNamespace(is_authenticated=True, is_superuser=True, pk=1))
    return client


@pytest.mark.parametrize("path,feature,selector", STATUS_ENDPOINTS)
def test_status_endpoint_is_independent(summary_client, monkeypatch, path, feature, selector):
    module = import_module(f"core.labs.features.{feature}.api.views")
    payload = {"total_count": 0, "unknown_status_count": 0, "statuses": []}
    query = Mock(return_value=payload)
    monkeypatch.setattr(module, selector, query)
    response = summary_client.get(f"/api/labs/{path}")
    assert response.status_code == 200
    assert response.json() == {"data": payload}
    query.assert_called_once_with()
    assert "X-Request-ID" in response


@pytest.mark.parametrize("path,feature,selector", STATUS_ENDPOINTS)
@pytest.mark.parametrize("query", ["owner_id=1", "page=1", "page_size=10"])
def test_unknown_queries_rejected_before_aggregation(summary_client, monkeypatch, path, feature, selector, query):
    module = import_module(f"core.labs.features.{feature}.api.views")
    query = Mock()
    monkeypatch.setattr(module, selector, query)
    response = summary_client.get(f"/api/labs/{path}?{query}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"
    query.assert_not_called()


@pytest.mark.parametrize("path,feature,selector", STATUS_ENDPOINTS)
def test_unauthenticated_user_denied_without_api_key_lookup(
    summary_contract_settings, monkeypatch, path, feature, selector
):
    from rest_framework_api_key.permissions import HasAPIKey

    monkeypatch.setattr(HasAPIKey, "has_permission", lambda *args: False)
    module = import_module(f"core.labs.features.{feature}.api.views")
    query = Mock()
    monkeypatch.setattr(module, selector, query)
    response = APIClient().get(f"/api/labs/{path}")
    assert response.status_code in (401, 403)
    assert set(response.json()) == {"error"}
    query.assert_not_called()


@pytest.mark.parametrize(
    "feature,path,selector,row",
    [
        (
            "licenses",
            "licenses/categories/summary",
            "list_license_category_summary",
            {"category_id_value": 2, "category_name": None, "resource_count": 4},
        ),
    ],
)
def test_license_category_counts_are_separate_and_paginated(summary_client, monkeypatch, feature, path, selector, row):
    module = import_module(f"core.labs.features.{feature}.api.views")
    monkeypatch.setattr(module, selector, lambda: [row, row])
    response = summary_client.get(f"/api/labs/{path}?page_size=1")
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert set(body["data"][0]) == {"id", "name", "resource_count"}
    assert body["meta"]["pagination"]["count"] == 2
    assert body["meta"]["pagination"]["next"] is not None
    assert summary_client.get(f"/api/labs/{path}?page_size=101").status_code == 400


def test_combined_dashboard_route_removed():
    with pytest.raises(Resolver404):
        resolve("/api/labs/dashboard/resource-summary")


def test_equipment_status_summary_takes_an_optional_category(summary_client, monkeypatch):
    """Per-category summary routes are gone (step 6); ``?category=<id>`` narrows the one summary."""
    from core.labs.features.equipment.api import views

    query = Mock(return_value={"total_count": 2, "unknown_status_count": 1, "statuses": []})
    monkeypatch.setattr(views, "get_equipment_category_status_summary", query)
    response = summary_client.get("/api/labs/equipment/status-summary", {"category": 7})
    assert response.status_code == 200
    assert response.json()["data"]["total_count"] == 2
    query.assert_called_once_with(category_id=7)
    with pytest.raises(Resolver404):
        resolve("/api/labs/equipment/computing/summary")


def test_status_counts_include_unknown_and_zero_buckets():
    queryset = Mock()
    queryset.order_by.return_value.aggregate.return_value = {
        "total_count": 3,
        "status_available": 2,
        "status_broken": 0,
    }
    result = status_summary(queryset, field="status", choices=[("available", "Available"), ("broken", "Broken")])
    assert result["unknown_status_count"] == 1
    assert result["statuses"][1] == {"status": {"value": "broken", "label": "Broken"}, "resource_count": 0}
