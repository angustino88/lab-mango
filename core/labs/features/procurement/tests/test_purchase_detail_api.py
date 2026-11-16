"""HTTP contract of ``GET /purchases/{id}`` and ``PATCH /purchases/{id}/draft`` (one serialization pass)."""

import pytest
from rest_framework.test import APIClient

from core.users.models import User
from tests.factories import grant_labs_role

pytestmark = pytest.mark.django_db

LIST_URL = "/api/labs/purchases"


@pytest.fixture
def client():
    admin = grant_labs_role(User.objects.create_user(username="purchase-detail-admin", display_name="Admin"), "admin")
    result = APIClient()
    result.force_authenticate(admin)
    return result


@pytest.fixture
def purchase_id(client):
    response = client.post(
        LIST_URL,
        {
            "supplier": "Detail supplier",
            "purchase_date": "2026-11-01",
            "total": {"amount": "100.00", "currency": "EUR"},
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()["data"]["id"]


def test_purchase_detail_returns_status_as_a_choice_and_an_etag(client, purchase_id):
    response = client.get(f"{LIST_URL}/{purchase_id}")

    assert response.status_code == 200, response.content
    assert response.json()["data"]["status"] == {"value": "draft", "label": "Draft"}
    assert response["ETag"]


def test_draft_header_patch_returns_the_updated_purchase(client, purchase_id):
    response = client.patch(
        f"{LIST_URL}/{purchase_id}/draft", {"supplier": "Renamed supplier"}, format="json", HTTP_IF_MATCH="*"
    )

    assert response.status_code == 200, response.content
    assert response.json()["data"]["supplier"] == "Renamed supplier"
    assert response.json()["data"]["status"] == {"value": "draft", "label": "Draft"}
