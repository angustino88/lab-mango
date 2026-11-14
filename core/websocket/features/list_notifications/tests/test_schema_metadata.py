"""Notification success envelopes match runtime without changing requests or errors."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.urls import path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework import generics
from rest_framework.test import APIRequestFactory, force_authenticate

from core.common.api.pagination import ResultsSetPagination
from core.websocket.features.list_notifications.api import NotificationListCreateView
from core.websocket.features.list_notifications.serializer import NotificationSerializer, NotificationWriteSerializer
from core.websocket.models import Notification


def resolve(document, schema):
    while "$ref" in schema:
        schema = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def test_get_schema_is_unchanged_and_post_schema_is_a_single_resource_envelope():
    class Baseline(generics.ListCreateAPIView):
        serializer_class = NotificationSerializer
        pagination_class = ResultsSetPagination
        queryset = Notification.objects.none()

    document = SchemaGenerator(patterns=[path("notifications", NotificationListCreateView.as_view())]).get_schema(
        public=True
    )
    baseline = SchemaGenerator(patterns=[path("notifications", Baseline.as_view())]).get_schema(public=True)
    operations = document["paths"]["/notifications"]
    assert operations["post"]["operationId"] == "notifications_create"
    before = baseline["paths"]["/notifications"]
    assert operations["post"].get("security") == before["post"].get("security")
    # RW-1: the request body is the write shape, not the read shape.
    request_schema = operations["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": "#/components/schemas/NotificationWrite"}
    post = operations["post"]
    assert set(post["responses"]) == {"201", "401"}
    created = resolve(document, post["responses"]["201"]["content"]["application/json"]["schema"])
    assert created["type"] == "object"
    assert set(created["properties"]) == {"data"}
    assert created["required"] == ["data"]
    payload = resolve(document, created["properties"]["data"])
    bare = resolve(document, before["post"]["responses"]["201"]["content"]["application/json"]["schema"])
    assert payload == bare
    assert payload["type"] == "object"
    assert set(payload["properties"]) == set(NotificationSerializer.Meta.fields)
    get = operations["get"]
    assert set(get["responses"]) == {"200", "400", "404"}
    envelope = resolve(document, get["responses"]["200"]["content"]["application/json"]["schema"])
    assert set(envelope["properties"]) == {"data", "meta"}
    assert set(envelope["required"]) == {"data", "meta"}
    assert envelope["properties"]["data"]["type"] == "array"
    meta = resolve(document, envelope["properties"]["meta"])
    pagination = resolve(document, meta["properties"]["pagination"])
    assert set(pagination["properties"]) == {"count", "page", "page_size", "next", "previous"}
    assert set(pagination["required"]) == set(pagination["properties"])
    for key in ("count", "page", "page_size"):
        assert pagination["properties"][key]["type"] == "integer"
    for key in ("next", "previous"):
        assert pagination["properties"][key]["type"] == "string"
        assert pagination["properties"][key]["nullable"] is True
    for code in ("400", "404"):
        error = resolve(document, get["responses"][code]["content"]["application/json"]["schema"])
        assert set(error["properties"]) == {"error"}


class SyntheticNotifications(NotificationListCreateView):
    def get_queryset(self):
        now = timezone.now()
        return [
            Notification(pk=i, message="Synthetic", expiry_date=now + timedelta(days=1), created=now, modified=now)
            for i in range(1, 4)
        ]


def call_view(method, query="", data=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)("/notifications" + query, data, format="json")
    force_authenticate(request, user=SimpleNamespace(pk=1, is_authenticated=True))
    return SyntheticNotifications.as_view()(request)


@pytest.mark.parametrize("query,page", [("", 1), ("?page_size=2", 1), ("?page_size=2&page=2", 2)])
def test_runtime_get_pagination_matches_documented_envelope(query, page):
    response = call_view("get", query)
    assert response.status_code == 200
    assert set(response.data) == {"data", "meta"}
    pagination = response.data["meta"]["pagination"]
    assert set(pagination) == {"count", "page", "page_size", "next", "previous"}
    assert pagination["count"] == 3
    assert pagination["page"] == page
    assert pagination["page_size"] == (2 if query else 25)
    assert len(response.data["data"]) == (1 if page == 2 else 2 if query else 3)


@pytest.mark.parametrize(
    "query,status,code",
    [
        ("?page_size=0", 400, "malformed_request"),
        ("?page_size=101", 400, "malformed_request"),
        ("?page_size=bad", 400, "malformed_request"),
        ("?page=999", 404, "not_found"),
        ("?page=bad", 404, "not_found"),
    ],
)
def test_documented_errors_are_reachable_runtime_paths(query, status, code):
    response = call_view("get", query)
    assert response.status_code == status
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == code


def test_post_runtime_returns_201_envelope_and_preserves_writable_fields_and_headers(monkeypatch):
    from jsonschema import validate

    def create(serializer, validated_data):
        assert set(validated_data) == {"message", "expiry_date"}
        now = timezone.now()
        return Notification(pk=7, created=now, modified=now, **validated_data)

    monkeypatch.setattr(NotificationWriteSerializer, "create", create)

    def success_headers(view, data):
        assert set(data) == set(NotificationSerializer.Meta.fields)
        assert data["id"] == 7
        return {"Location": "/notifications/7", "X-Synthetic-Create": "preserved"}

    monkeypatch.setattr(NotificationListCreateView, "get_success_headers", success_headers)
    response = call_view("post", data={"message": "Synthetic", "expires_at": "2099-01-01T00:00:00Z"})
    assert response.status_code == 201
    assert set(response.data) == {"data"}
    assert response.data["data"]["id"] == 7
    assert response.data["data"]["message"] == "Synthetic"
    assert set(response.data["data"]) == set(NotificationSerializer.Meta.fields)
    assert response["Location"] == "/notifications/7"
    assert response["X-Synthetic-Create"] == "preserved"
    document = SchemaGenerator(patterns=[path("notifications", NotificationListCreateView.as_view())]).get_schema(
        public=True
    )
    schema = document["paths"]["/notifications"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]
    schema = resolve(document, schema)
    schema = {
        **schema,
        "components": document["components"],
        "properties": {
            **schema["properties"],
            "data": {
                **resolve(document, schema["properties"]["data"]),
                "properties": {
                    **resolve(document, schema["properties"]["data"])["properties"],
                    "target_user": {"type": ["integer", "null"]},
                },
            },
        },
    }
    validate(response.data, schema)


@pytest.mark.parametrize(
    "body,status,code",
    [('{', 400, "malformed_request"), ('{}', 422, "validation_failed"),
     ('{"message": "Synthetic", "expires_at": "not-a-date"}', 422, "validation_failed")],
)
def test_post_errors_remain_unwrapped_and_do_not_create(monkeypatch, body, status, code):
    def unexpected_create(*args, **kwargs):
        pytest.fail("Invalid input must not create a notification")

    monkeypatch.setattr(NotificationWriteSerializer, "create", unexpected_create)
    request = APIRequestFactory().post("/notifications", body, content_type="application/json")
    force_authenticate(request, user=SimpleNamespace(pk=1, is_authenticated=True))
    response = NotificationListCreateView.as_view()(request)
    assert response.status_code == status
    assert set(response.data) == {"error"}
    assert set(response.data["error"]) == {"code", "message", "details", "request_id"}
    assert response.data["error"]["code"] == code


@pytest.mark.parametrize("authorization", [None, "Bearer", "Bearer synthetic-invalid-token"])
def test_post_authentication_error_matches_documentation(authorization):
    from jsonschema import validate

    headers = {} if authorization is None else {"HTTP_AUTHORIZATION": authorization}
    response = NotificationListCreateView.as_view()(
        APIRequestFactory().post("/notifications", {}, format="json", **headers)
    )
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert response.data["error"]["code"] == "unauthenticated"
    document = SchemaGenerator(patterns=[path("notifications", NotificationListCreateView.as_view())]).get_schema(
        public=True
    )
    schema = document["paths"]["/notifications"]["post"]["responses"]["401"]["content"]["application/json"]["schema"]
    validate(response.data, {**schema, "components": document["components"]})
