"""Cross-feature evidence for schema-only error documentation; no database access."""

import inspect
import json

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.urls import path, resolve
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.views import SpectacularAPIView
from rest_framework.test import APIRequestFactory, force_authenticate

from config.features.schema.urls import SchemaAPIView

# One reference-data route for every category since redesign step 6.
REFERENCE_PATHS = ("/api/labs/equipment/reference-data",)
SCHEMA_MEDIA_TYPES = (
    "application/vnd.oai.openapi",
    "application/yaml",
    "application/vnd.oai.openapi+json",
    "application/json",
)


def assert_error(document, response, media_type="application/json"):
    shape = response["content"][media_type]["schema"]
    while "$ref" in shape:
        shape = document["components"]["schemas"][shape["$ref"].rsplit("/", 1)[-1]]
    assert set(shape["properties"]) == {"error"}
    inner = shape["properties"]["error"]
    while "$ref" in inner:
        inner = document["components"]["schemas"][inner["$ref"].rsplit("/", 1)[-1]]
    assert set(inner["properties"]) == {"code", "message", "details", "request_id"}
    assert inner["properties"]["details"]["type"] == "array"


@pytest.mark.parametrize("endpoint", REFERENCE_PATHS)
def test_equipment_reference_docs_match_anonymous_denial(endpoint):
    callback = resolve(endpoint).func
    view_class = getattr(callback, "view_class")
    document = SchemaGenerator(patterns=[path(endpoint.lstrip("/"), view_class.as_view())]).get_schema(public=True)
    operation = document["paths"][endpoint]["get"]
    # 400 documents an invalid optional ``category`` query parameter.
    assert set(operation["responses"]) == {"200", "400", "401"}
    assert_error(document, operation["responses"]["401"])
    request = APIRequestFactory().get(endpoint)
    response = async_to_sync(callback)(request)
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert response.data["error"]["code"] == "unauthenticated"
    assert set(response.data["error"]) == {"code", "message", "details", "request_id"}


def test_schema_docs_preserve_success_and_third_party_runtime_configuration():
    document = SchemaGenerator(patterns=[path("schema/", SchemaAPIView.as_view())]).get_schema(public=True)
    original = SchemaGenerator(patterns=[path("schema/", SpectacularAPIView.as_view())]).get_schema(public=True)
    responses = document["paths"]["/schema/"]["get"]["responses"]
    assert responses["200"] == original["paths"]["/schema/"]["get"]["responses"]["200"]
    assert set(responses) == {"200", "401", "403"}
    for status in ("401", "403"):
        assert set(responses[status]["content"]) == set(SCHEMA_MEDIA_TYPES)
        for media_type in SCHEMA_MEDIA_TYPES:
            assert_error(document, responses[status], media_type)
    assert SchemaAPIView.permission_classes is SpectacularAPIView.permission_classes
    assert SchemaAPIView.authentication_classes is SpectacularAPIView.authentication_classes
    assert SchemaAPIView.renderer_classes is SpectacularAPIView.renderer_classes
    assert inspect.unwrap(SchemaAPIView.get) is inspect.unwrap(SpectacularAPIView.get)


@pytest.mark.parametrize("media_type", SCHEMA_MEDIA_TYPES)
@pytest.mark.parametrize(
    "authenticated,status,code", [(False, 401, "unauthenticated"), (True, 403, "permission_denied")]
)
def test_schema_error_envelope_and_negotiated_wire_format(media_type, authenticated, status, code):
    request = APIRequestFactory().get("/api/schema/", HTTP_ACCEPT=media_type)
    if authenticated:
        force_authenticate(request, user=get_user_model()(is_staff=False))
    response = SchemaAPIView.as_view()(request)
    response.render()
    assert response.status_code == status
    assert response["Content-Type"].split(";")[0] == media_type
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == code
    assert set(response.data["error"]) == {"code", "message", "details", "request_id"}
    if status == 401:
        assert response["WWW-Authenticate"].startswith("Bearer")
    if media_type in ("application/json", "application/vnd.oai.openapi+json"):
        assert json.loads(response.content) == response.data
    else:
        import yaml

        assert yaml.safe_load(response.content) == response.data
