"""Public bench detail contract: lean response and no supported query parameters."""

import pytest
from django.db import IntegrityError
from django.urls import path
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.views import APIView

from core.labs.features.benches.api.serializers import BenchSerializer
from tests.factories import BenchFactory, UserFactory, grant_labs_role

pytestmark = pytest.mark.django_db


class _IntegrityErrorAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        raise IntegrityError("sensitive database constraint details")


urlpatterns = [path("integrity-error", _IntegrityErrorAPIView.as_view())]


def test_global_handler_sanitizes_integrity_error_through_actual_api_invocation(settings):
    settings.ROOT_URLCONF = __name__
    settings.MIDDLEWARE = []
    request_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    response = APIClient().get("/integrity-error", HTTP_X_REQUEST_ID=request_id)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response["X-Request-ID"] == request_id
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": [],
            "request_id": request_id,
        }
    }
    assert "sensitive database" not in response.content.decode()


@pytest.fixture()
def bench_api(monkeypatch, settings):
    settings.ROOT_URLCONF = "core.labs.features.benches.tests.detail_urls"
    settings.MIDDLEWARE = [item for item in settings.MIDDLEWARE if not item.startswith("allauth.")]
    user = UserFactory()
    bench = BenchFactory()
    client = APIClient()
    grant_labs_role(user, "coord")
    client.force_authenticate(user)
    return client, bench


def test_bench_detail_returns_exact_lean_serializer_fields(bench_api):
    client, bench = bench_api

    response = client.get(f"/api/labs/benches/{bench.pk}")

    assert response.status_code == 200
    assert set(response.data["data"]) == set(BenchSerializer.Meta.fields)
    assert response.data["data"]["equipment_url"] == f"/api/labs/benches/{bench.pk}/equipment"
    assert "equipment" not in response.data["data"]
    assert "booking_summary" not in response.data["data"]
    equipment_response = client.get(response.data["data"]["equipment_url"])
    assert equipment_response.status_code == 200


@pytest.mark.parametrize(
    "query",
    [
        "equipment_page=1",
        "equipment_page_size=20",
        "page=1",
        "page_size=20",
        "unexpected=1",
    ],
)
def test_bench_detail_rejects_all_query_parameters(bench_api, query):
    client, bench = bench_api

    response = client.get(f"/api/labs/benches/{bench.pk}?{query}")

    assert response.status_code == 400
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == "invalid_query"
    assert set(response.data["error"]) == {"code", "message", "details", "request_id"}


def test_bench_detail_rejects_repeated_query_parameter(bench_api):
    client, bench = bench_api

    response = client.get(f"/api/labs/benches/{bench.pk}?equipment_page=1&equipment_page=2")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "invalid_query"


def test_bench_detail_missing_resource_remains_404(bench_api):
    client, _ = bench_api

    response = client.get("/api/labs/benches/999999")

    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"


def test_bench_create_missing_reference_returns_field_scoped_422(bench_api):
    client, _ = bench_api

    response = client.post(
        "/api/labs/benches",
        {"sku": "MISSING-REFERENCE-TEST", "name": "Test bench", "setup_location_id": 999999},
        format="json",
    )

    assert response.status_code == 422
    assert response.data["error"]["code"] == "validation_failed"
    assert response.data["error"]["details"] == [
        {
            "field": "setup_location_id",
            "code": "does_not_exist",
            "message": "Select an existing setup location.",
        }
    ]


def test_bench_create_missing_group_returns_field_scoped_422(bench_api):
    client, _ = bench_api

    response = client.post(
        "/api/labs/benches",
        {"sku": "MISSING-GROUP-CREATE", "name": "Test bench", "group_id": 999999},
        format="json",
    )

    assert response.status_code == 422
    assert response.data["error"]["details"] == [
        {
            "field": "group_id",
            "code": "does_not_exist",
            "message": "Select an existing reference.",
        }
    ]


def test_bench_update_missing_group_returns_field_scoped_422(bench_api):
    client, bench = bench_api

    response = client.patch(f"/api/labs/benches/{bench.pk}", {"group_id": 999999}, format="json")

    assert response.status_code == 422
    assert response.data["error"]["details"] == [
        {
            "field": "group_id",
            "code": "does_not_exist",
            "message": "Select an existing reference.",
        }
    ]


def test_bench_list_and_write_keep_bench_serializer_shape(bench_api):
    client, bench = bench_api

    listed = client.get("/api/labs/benches")
    updated = client.patch(f"/api/labs/benches/{bench.pk}", {"name": "Updated bench"}, format="json")

    assert listed.status_code == 200
    assert set(listed.data["data"][0]) == set(BenchSerializer.Meta.fields)
    assert updated.status_code == 200
    assert set(updated.data["data"]) == set(BenchSerializer.Meta.fields)
    assert updated.data["data"]["equipment_url"].endswith(f"/api/labs/benches/{bench.pk}/equipment/")


def test_bench_detail_equipment_url_does_not_change_list_url(bench_api):
    client, bench = bench_api
    detail = client.get(f"/api/labs/benches/{bench.pk}")
    listed = client.get("/api/labs/benches")

    assert detail.data["data"]["equipment_url"] == f"/api/labs/benches/{bench.pk}/equipment"
    assert listed.data["data"][0]["equipment_url"].endswith(f"/api/labs/benches/{bench.pk}/equipment/")


def test_bench_detail_requires_authentication(bench_api):
    _, bench = bench_api

    response = APIClient().get(f"/api/labs/benches/{bench.pk}")

    assert response.status_code == 401
