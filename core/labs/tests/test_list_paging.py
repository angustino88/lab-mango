"""page / page_size on the paginated labs lists that previously left them out of OpenAPI.

The paginator always honoured both parameters; these tests pin the runtime behaviour
the contract now documents, for FilterSpec lists and catalog (options-backed) lists alike.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.labs.models import EquipmentCategory, EquipmentKind, Room

pytestmark = pytest.mark.django_db

PAGED_LISTS = (
    "/api/labs/benches",
    "/api/labs/buildings",
    "/api/labs/cities",
    "/api/labs/equipment",
    "/api/labs/equipment-kinds",
    "/api/labs/equipment-manufacturers",
    "/api/labs/equipment-product-models",
    "/api/labs/equipment-types",
    "/api/labs/license-products",
    "/api/labs/licenses",
    "/api/labs/resource-groups",
    "/api/labs/rooms",
    "/api/labs/stations",
)


@pytest.fixture
def admin_client():
    client = APIClient()
    user = get_user_model().objects.create_user(username="list-paging-admin", is_staff=True, is_superuser=True)
    client.force_authenticate(user)
    return client


@pytest.mark.parametrize("path", PAGED_LISTS)
def test_page_size_is_honoured(admin_client, path):
    response = admin_client.get(path, {"page": 1, "page_size": 1})
    assert response.status_code == 200, response.data
    assert len(response.data["data"]) <= 1
    pagination = response.data["meta"]["pagination"]
    assert (pagination["page"], pagination["page_size"]) == (1, 1)


@pytest.mark.parametrize("path", PAGED_LISTS)
@pytest.mark.parametrize(("query", "code"), [({"page": 0}, "invalid_query"), ({"page_size": 101}, "max_value")])
def test_invalid_paging_is_rejected(admin_client, path, query, code):
    response = admin_client.get(path, query)
    assert response.status_code == 400, response.data
    assert response.data["error"]["code"] == "invalid_query"
    [detail] = response.data["error"]["details"]
    assert (detail["field"], detail["code"]) == (next(iter(query)), code)


def test_filter_spec_list_pages_with_filters(admin_client):
    prefix = uuid.uuid4().hex[:6]
    for index in range(3):
        Room.objects.create(sku=f"PG-{prefix}-{index}", name=f"Paging room {prefix} {index}")
    response = admin_client.get("/api/labs/rooms", {"q": prefix, "ordering": "sku", "page": 2, "page_size": 2})
    assert response.status_code == 200, response.data
    assert [row["sku"] for row in response.data["data"]] == [f"PG-{prefix}-2"]
    assert response.data["meta"]["pagination"]["count"] == 3


def test_catalog_list_pages_with_filters(admin_client):
    category = EquipmentCategory.objects.create(key="paging", name="Paging", definition="Paging")
    for index in range(3):
        EquipmentKind.objects.create(category=category, name=f"Paging kind {index}")
    response = admin_client.get("/api/labs/equipment-kinds", {"category_id": category.pk, "page": 2, "page_size": 2})
    assert response.status_code == 200, response.data
    assert len(response.data["data"]) == 1
    assert response.data["meta"]["pagination"]["count"] == 3
