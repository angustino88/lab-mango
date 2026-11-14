"""Cross-feature schema regressions; direct execution uses secret-free, non-DB settings."""

if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ.pop("DJANGO_SETTINGS_MODULE", None)
    from django.conf import settings

    settings.configure(
        SECRET_KEY="synthetic-test-only",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
            "rest_framework_api_key",
            "core.common",
            "core.reference_data",
            "core.users",
            "core.agents",
            "core.routing",
            "core.labs",
            "core.support_desk",
        ],
        AUTH_USER_MODEL="users.User",
        ALLOWED_HOSTS=["testserver"],
        DATABASES={},
        REST_FRAMEWORK={"DEFAULT_SCHEMA_CLASS": "config.schema.ProjectAutoSchema"},
        SPECTACULAR_SETTINGS={"POSTPROCESSING_HOOKS": []},
    )
    import django

    django.setup()

    import pytest

    raise SystemExit(
        pytest.main(
            [
                "-c",
                "packages/drf-api-contracts/pyproject.toml",
                "--confcutdir=tests/unit",
                "-p",
                "no:django",
                *(sys.argv[1:] or [__file__]),
                "-q",
                "--tb=short",
            ]
        )
    )

import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import models
from django.http import QueryDict
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from core.common.api.options import OptionsAPIView, OptionsQueryMixin, SizeClass
from core.common.api.reference_views import reference_urlpatterns
from core.labs.features.procurement.api import serializers as procurement
from core.support_desk.features.tickets.api import serializers as tickets


def serializer_schema(serializer_class, direction="response"):
    class SchemaView(APIView):
        authentication_classes = []
        permission_classes = []

        @extend_schema(request=serializer_class, responses=serializer_class)
        def post(self, request):
            raise NotImplementedError

    document = SchemaGenerator(patterns=[path("schema-test", SchemaView.as_view())]).get_schema(public=True)
    operation = document["paths"]["/schema-test"]["post"]
    body = operation["requestBody"] if direction == "request" else operation["responses"]["200"]
    return document, resolve(document, body["content"]["application/json"]["schema"])


def resolve(document, schema):
    while "$ref" in schema:
        schema = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


@pytest.mark.parametrize(
    "serializer_class,field,method",
    [
        # `None`: a MoneyField (FMT-2), rendered through the field itself.
        (procurement.PurchaseItemReadSerializer, "unit_price", None),
        (procurement.PurchaseItemReadSerializer, "line_value", "get_line_value"),
        (procurement.PurchaseDetailSerializer, "total", None),
        (procurement.PurchaseDetailSerializer, "lines_total", "get_lines_total"),
        (procurement.PurchaseDraftHeaderOutputSerializer, "total", None),
        (procurement.PurchaseSerializer, "total", None),
        (procurement.PurchaseItemResourceSerializer, "acquisition_price", "get_acquisition_price"),
    ],
)
def test_money_schema_matches_existing_getter(serializer_class, field, method):
    document, schema = serializer_schema(serializer_class)
    money = resolve(document, schema["properties"][field])
    if "allOf" in money:  # a read-only $ref is wrapped as allOf: [{$ref}]
        money = resolve(document, money["allOf"][0])
    assert money["type"] == "object"
    assert set(money["properties"]) == {"amount", "currency"}
    assert set(money["required"]) == {"amount", "currency"}
    amount = money["properties"]["amount"]
    assert amount["type"] == "string"
    assert money["properties"]["currency"]["type"] == "string"
    purchase = SimpleNamespace(currency="EUR")
    obj = SimpleNamespace(
        unit_price=Decimal("12.30"),
        quantity=2,
        total_amount=Decimal("24.60"),
        items_total=Decimal("24.60"),
        acquisition_price=Decimal("12.30"),
        currency="EUR",
        purchase=purchase,
        purchase_item=SimpleNamespace(purchase=purchase),
    )
    serializer = serializer_class()
    payload = getattr(serializer, method)(obj) if method else serializer.fields[field].to_representation(obj)
    expected = "12.30" if field in {"unit_price", "acquisition_price"} else "24.60"
    assert payload == {"amount": expected, "currency": "EUR"}
    assert re.fullmatch(amount["pattern"], payload["amount"])
    assert not re.fullmatch(amount["pattern"], "1e2")


@pytest.mark.parametrize(
    "serializer_class,payload",
    [
        (tickets.AdminCategoryCreateSerializer, {"name": "Synthetic category"}),
        (tickets.AdminPriorityCreateSerializer, {"name": "Synthetic priority", "rank": 1}),
        (tickets.AdminTeamCreateSerializer, {"name": "Synthetic team"}),
    ],
)
def test_optional_slug_schema_preserves_defaults_and_validation(serializer_class, payload):
    _, schema = serializer_schema(serializer_class, "request")
    # Documented as oneOf(slug with default "", empty string); check the slug branch.
    documented = schema["properties"]["code"]
    code = next(branch for branch in documented.get("oneOf", [documented]) if "pattern" in branch)
    assert code["default"] == ""
    assert code["maxLength"] == 50
    assert "code" not in schema.get("required", [])
    for value in ("", "Synthetic_code-1"):
        serializer = serializer_class(data={**payload, "code": value})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["code"] == value
        assert re.fullmatch(code["pattern"], value)
    serializer = serializer_class(data=payload)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["code"] == ""
    for value in ("bad code!", "x" * 51, None):
        serializer = serializer_class(data={**payload, "code": value})
        assert not serializer.is_valid()
        assert "code" in serializer.errors
    assert not re.fullmatch(code["pattern"], "bad code!")


class DocumentationOptionsView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    schema_description = "Synthetic selector for documentation regression tests."
    max_results = 1

    def select(self, *, actor, filters):
        return [{"id": 1, "sku": None, "name": "Synthetic option"}]


def test_options_schema_preserves_success_caching_and_auth_contract():
    document = SchemaGenerator(patterns=[path("options", DocumentationOptionsView.as_view())]).get_schema(public=True)
    operation = document["paths"]["/options"]["get"]
    responses = operation["responses"]
    assert {"200", "304", "400", "403"} <= set(responses)
    assert "content" not in responses["304"]
    success = resolve(document, responses["200"]["content"]["application/json"]["schema"])
    assert set(success["properties"]) == {"data"}
    assert operation["security"]
    assert DocumentationOptionsView.permission_classes == OptionsAPIView.permission_classes
    error = resolve(document, responses["400"]["content"]["application/json"]["schema"])
    assert set(error["properties"]) == {"error"}
    inner = resolve(document, error["properties"]["error"])
    assert set(inner["properties"]) == {"code", "message", "details", "request_id"}
    assert inner["properties"]["details"]["type"] == "array"
    assert "status" not in inner["properties"]


@pytest.mark.parametrize("query", ["unknown=1", "q=", "q=a&q=b", "include_ids=0"])
def test_options_invalid_query_keeps_json_error_envelope(query):
    view = DocumentationOptionsView()
    view.request = SimpleNamespace(method="GET", query_params=QueryDict(query))
    _, response = view.validate_options_query(view.request)
    assert response.status_code == 400
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == "invalid_query"
    assert response.data["error"]["details"]
    assert set(response.data["error"]) == {"code", "message", "details", "request_id"}


def test_options_cap_required_filter_and_etag_behavior_is_unchanged():
    view = DocumentationOptionsView()
    view.request = SimpleNamespace(method="GET", query_params=QueryDict(), headers={}, user=None)
    view.size_class = SizeClass.LARGE
    view.required_any = ("q",)
    _, response = view.validate_options_query(view.request)
    assert response.data["error"]["code"] == "invalid_query"
    view.size_class = SizeClass.SMALL
    view.select = lambda **kwargs: [{"id": i, "sku": None, "name": "Synthetic"} for i in (1, 2)]
    response = view.handle_get(view.request)
    assert response.status_code == 400
    assert response.data["error"]["code"] == "too_many_results"
    assert response.data["error"]["details"] == []
    assert response["Cache-Control"] == "no-store"
    del view.select
    response = view.handle_get(view.request)
    assert response.status_code == 200
    assert response.data == {"data": [{"id": 1, "sku": None, "name": "Synthetic option"}]}
    view.request.headers["If-None-Match"] = response["ETag"]
    cached = view.handle_get(view.request)
    assert cached.status_code == 304
    assert cached.data is None
    assert cached["ETag"] == response["ETag"]


class DocumentationReference(models.Model):
    name: models.CharField = models.CharField(max_length=50)
    active: models.BooleanField = models.BooleanField(default=True)

    class Meta:
        app_label = "common"
        managed = False


def test_reference_factory_descriptions_preserve_callbacks_and_create_headers():
    calls = []
    resource = SimpleNamespace(model=DocumentationReference, fields=("name", "active"), label="name", key="synthetic")

    def create(resource, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data={"id": 7, "name": "Synthetic reference", "active": True}, replayed=True)

    patterns = reference_urlpatterns(
        resource=resource,
        prefix="references",
        tag="Synthetic references",
        module=__name__,
        create=create,
        listing=lambda *args, **kwargs: [],
        retrieve=lambda *args, **kwargs: {},
    )
    document = SchemaGenerator(patterns=patterns).get_schema(public=True)
    collection = document["paths"]["/references"]
    detail = document["paths"]["/references/{reference_id}"]["get"]
    for operation in (collection["get"], collection["post"], detail):
        assert operation["description"]
        assert operation["tags"] == ["Synthetic references"]
    assert "paginated" in collection["get"]["description"].lower()
    assert "Idempotency-Key" in collection["post"]["description"]
    assert "Location" in collection["post"]["description"]
    assert "404" in detail["description"]
    assert {"201", "400", "409", "422"} <= set(collection["post"]["responses"])
    view = patterns[0].callback.view_class()
    assert view.permission_classes == [IsAuthenticated]
    request = APIRequestFactory().post("/references", {"name": "Synthetic reference"}, format="json")
    request = view.initialize_request(request)
    request.user = SimpleNamespace(is_authenticated=True)
    view.request = request
    response = view.handle_post(request)
    assert response.status_code == 201
    assert response["Location"] == "http://testserver/references/7"
    assert response["Idempotency-Replayed"] == "true"
    assert calls[0]["values"] == {"name": "Synthetic reference"}
    assert calls[0]["actor"] is request.user
