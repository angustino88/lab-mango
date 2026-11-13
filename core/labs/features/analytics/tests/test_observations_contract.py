"""Database-free runtime/schema regressions for observations and pagination audit."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.urls import path
from drf_api_contracts import ResponseSchemaFactory
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema, extend_schema_serializer, extend_schema_view
from drf_spectacular.validation import validate_schema
from jsonschema import Draft202012Validator
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.labs.features.analytics.api.observations import views
from core.websocket.features.list_notifications.api import NotificationListCreateView
from core.websocket.features.list_notifications.serializer import NotificationSerializer

CASES = (
    ("booking", views.BookingCountAPIView, "get_booking_volume_metrics", "BookingCountAnalyticsResponse"),
    ("lab-count", views.LabCountAPIView, "get_active_bench_metrics", "LabCountAnalyticsResponse"),
    ("user-count", views.UserCountAPIView, "get_active_user_metrics", "UserCountAnalyticsResponse"),
    ("lab-visits", views.LabVisitsAPIView, "get_facility_visit_metrics", "LabVisitAnalyticsResponse"),
)
BASE = "/api/labs/analytics/"
urlpatterns = [path(f"api/labs/analytics/{name}", view.as_view()) for name, view, _, _ in CASES]
urlpatterns += [path("api/websocket/notifications", NotificationListCreateView.as_view())]


@pytest.fixture(scope="module")
def schema():
    document = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
    validate_schema(document)
    return document


def _json_schema(node):
    """Translate OpenAPI 3.0 ``nullable: true`` into JSON Schema 2020-12 (``type: [T, "null"]``)."""
    if isinstance(node, list):
        return [_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: _json_schema(value) for key, value in node.items()}
    if node.pop("nullable", False):
        if "type" in node:
            node["type"] = [node["type"], "null"]
        else:
            node = {"anyOf": [node, {"type": "null"}]}
    return node


def response_validator(schema, endpoint, method="get", status_code=200):
    response_schema = schema["paths"][endpoint][method]["responses"][str(status_code)]["content"]["application/json"][
        "schema"
    ]
    return Draft202012Validator(_json_schema({**response_schema, "components": schema["components"]}))


@pytest.mark.parametrize("name,view_class,query,component", CASES)
@pytest.mark.parametrize(
    "unit,payload",
    [
        (None, {"count": 3, "trend": -2.5}),
        ("day", [{"date": "2026-11-09", "count": 3}]),
        ("week", [{"year": 2026, "week": 46, "count": 3}]),
        ("month", [{"year": 2026, "month": 11, "count": 3}]),
        ("quarter", [{"year": 2026, "quarter": 4, "count": 3}]),
        ("year", [{"year": 2026, "count": 3}]),
        ("day", []),
    ],
)
def test_get_runtime_matches_nested_polymorphic_envelope(schema, name, view_class, query, component, unit, payload):
    endpoint = BASE + name
    request = Request(APIRequestFactory().get(endpoint, {} if unit is None else {"unit": unit}))
    view = view_class()
    view.request = request
    with patch.object(views, query, return_value=payload) as metric_query:
        response = view.handle_get(request)
    metric_query.assert_called_once_with(unit=unit, date_after=None, date_before=None)
    assert response.status_code == 200
    assert response.data == {"data": payload}
    validator = response_validator(schema, endpoint)
    validator.validate(response.data)
    assert not validator.is_valid(payload)
    assert not validator.is_valid({})
    assert not validator.is_valid({"data": {"count": 3}})
    assert not validator.is_valid({"data": [{"date": "2026-11-09"}]})
    envelope = schema["components"]["schemas"][component]
    assert envelope["type"] == "object"
    assert "data" in envelope["required"]
    payload_ref = envelope["properties"]["data"]["$ref"].rsplit("/", 1)[-1]
    variants = schema["components"]["schemas"][payload_ref]["oneOf"]
    assert len(variants) == 2
    assert variants[0]["$ref"].endswith("/AnalyticsCountTrend")
    assert variants[1] == {"type": "array", "items": {"$ref": "#/components/schemas/AnalyticsAggregatedLog"}}
    contract = view_class.get_contract.responses.success
    # Schema-only contracts must not introduce serializer validation or pagination.
    assert contract.payload_serializer is None
    assert contract.many is False
    assert contract.is_paginated is False


@pytest.mark.parametrize("name,view_class,query,component", CASES)
def test_get_query_and_status_documentation_is_preserved(schema, name, view_class, query, component):
    operation = schema["paths"][BASE + name]["get"]
    assert set(operation["responses"]) == {"200", "400"}
    assert operation["tags"] == ["Analytics"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {"unit", "date_after", "date_before"}
    assert all(p["in"] == "query" and not p.get("required", False) for p in parameters.values())
    assert parameters["unit"]["schema"]["enum"] == ["day", "week", "month", "quarter", "year"]
    assert parameters["date_after"]["schema"]["format"] == "date"
    assert parameters["date_before"]["schema"]["format"] == "date"


@pytest.mark.parametrize("name,view_class,query,component", CASES)
@pytest.mark.parametrize(
    "params",
    [
        {"unit": "hour"},
        {"date_after": "2026-11-01"},
        {"unit": "day", "date_after": "2026-11-10", "date_before": "2026-11-10"},
        {"unit": "day", "date_after": "2024-01-01", "date_before": "2026-01-01"},
        {"unit": "week", "date_after": "2026-11-10", "date_before": "2026-11-01"},
        {"unit": "day", "date_after": "2026-02-30"},
        {"unit": "day", "since": "2026-11-01"},
    ],
)
def test_get_rejects_invalid_query_without_calling_the_selector(name, view_class, query, component, params):
    request = Request(APIRequestFactory().get(BASE + name, params))
    view = view_class()
    view.request = request
    with patch.object(views, query) as metric_query:
        response = view.handle_get(request)
    assert response.status_code == 400
    metric_query.assert_not_called()


@pytest.mark.parametrize("name,view_class,query,component", CASES)
def test_get_passes_a_valid_day_range_to_the_selector(name, view_class, query, component):
    params = {"unit": "day", "date_after": "2026-10-14", "date_before": "2026-11-14"}
    request = Request(APIRequestFactory().get(BASE + name, params))
    view = view_class()
    view.request = request
    with patch.object(views, query, return_value=[]) as metric_query:
        response = view.handle_get(request)
    assert response.status_code == 200
    metric_query.assert_called_once_with(unit="day", date_after=date(2026, 10, 14), date_before=date(2026, 11, 14))


@pytest.mark.parametrize("valid", [True, False])
def test_visit_post_body_status_and_validation_are_unchanged(schema, valid):
    endpoint = BASE + "lab-visits"
    payload = {"facility_identifier": "synthetic-lab"} if valid else {"facility_identifier": ["invalid"]}
    request = Request(APIRequestFactory().post(endpoint, payload, format="json"))
    # Direct handler invocation avoids authentication/database work, not response logic.
    request._full_data = payload
    request.user = SimpleNamespace(pk=10001)
    view = views.LabVisitsAPIView()
    view.request = request
    event = SimpleNamespace(pk=42, facility_identifier="synthetic-lab", occurred_at="2026-11-09T12:00:00Z")
    with patch.object(views, "record_facility_visit", return_value=event) as record:
        response = view.handle_post(request)
    assert response.status_code == (200 if valid else 400)
    response_validator(schema, endpoint, "post", response.status_code).validate(response.data)
    if valid:
        assert response.data == {
            "data": {"id": 42, "facility_identifier": "synthetic-lab", "occurred_at": event.occurred_at}
        }
        record.assert_called_once()
        assert record.call_args.kwargs["actor"] is request.user
    else:
        record.assert_not_called()
        assert response.data["error"]["code"] == "validation_failed"
    assert set(schema["paths"][endpoint]["post"]["responses"]) == {"200", "400", "422"}


@pytest.mark.parametrize(
    "rows,page", [([], 1), ([{"id": 1}, {"id": 2}, {"id": 3}], 1), ([{"id": 1}, {"id": 2}, {"id": 3}], 2)]
)
def test_websocket_get_pagination_audit_and_precise_candidate(schema, rows, page):
    rows = [
        {
            **row,
            "message": "Synthetic notification",
            "details": "Synthetic details",
            "message_type": "info",
            "expiry_date": "2026-11-10T12:00:00Z",
            "target_user": None,
            "created": "2026-11-09T12:00:00Z",
            "modified": "2026-11-09T12:00:00Z",
        }
        for row in rows
    ]
    endpoint = "/api/websocket/notifications"
    request = Request(APIRequestFactory().get(endpoint, {"page": page, "page_size": 2}))
    view = NotificationListCreateView()
    view.request = request
    view.format_kwarg = None
    # Exercise DRF's actual list and paginator; synthetic rows replace only ORM and serialization.
    with (
        patch.object(view, "get_queryset", return_value=rows),
        patch.object(view, "get_serializer", side_effect=lambda data, **kwargs: SimpleNamespace(data=data)),
    ):
        response = view.list(request)
    assert response.status_code == 200
    assert response.data == {
        "data": rows[(page - 1) * 2 : page * 2],
        "meta": {
            "pagination": {
                "count": len(rows),
                "page": page,
                "page_size": 2,
                "next": "http://testserver/api/websocket/notifications?page=2&page_size=2"
                if len(rows) > 2 and page == 1
                else None,
                "previous": "http://testserver/api/websocket/notifications?page_size=2" if page == 2 else None,
            }
        },
    }
    get_schema = schema["paths"][endpoint]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    actual_component = schema["components"]["schemas"][get_schema["$ref"].rsplit("/", 1)[-1]]
    # The documented GET schema now matches the runtime envelope (it used to advertise
    # DRF's count/next/previous/results); keep runtime and documentation aligned.
    assert set(actual_component["properties"]) == {"data", "meta"}
    assert response_validator(schema, endpoint).is_valid(response.data)
    # Prove a local, GET-only annotation candidate, without changing production or POST.
    candidate = ResponseSchemaFactory.paginated("NotificationListCreateView", NotificationSerializer)
    extend_schema_serializer(many=False)(candidate)
    candidate_view = type("CandidateNotificationListCreateView", (NotificationListCreateView,), {})
    extend_schema_view(get=extend_schema(responses={200: candidate}))(candidate_view)
    candidate_schema = SchemaGenerator(
        patterns=[path("api/websocket/notifications", candidate_view.as_view())]
    ).get_schema(request=None, public=True)
    validate_schema(candidate_schema)
    candidate_ref = candidate_schema["paths"][endpoint]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    candidate_component = candidate_schema["components"]["schemas"][candidate_ref["$ref"].rsplit("/", 1)[-1]]
    assert set(candidate_component["properties"]) == {"data", "meta"}
    assert candidate_component["properties"]["data"]["type"] == "array"
    assert candidate_schema["paths"][endpoint]["post"] == schema["paths"][endpoint]["post"]
    response_validator(candidate_schema, endpoint).validate(response.data)
