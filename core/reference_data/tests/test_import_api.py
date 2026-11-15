"""Cross-owner acceptance tests for explicit reference import catalogs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.urls import resolve
from rest_framework.test import APIClient

from core.labs.models import Department, EquipmentCategory, EquipmentKind
from core.reference_data.application import create_reference
from core.reference_data.contracts import CreateReferenceInput, ReferenceResource
from core.reference_data.models import ReferenceImportReceipt
from tests.factories import grant_labs_role

ROOT = "/api/labs/"
# Listed and retrieved only; rows come from provisioned defaults.
READ_ONLY_PATHS = frozenset({"equipment/reference-data/categories"})
PATHS = [
    *(
        f"equipment/reference-data/{key}"
        for key in (
            "categories",
            "kinds",
            "types",
            "manufacturers",
            "product-models",
            "specification-definitions",
            "product-model-specifications",
            "interfaces",
            "materials",
            "display-sizes",
            "display-resolutions",
            "networking-protocols",
            "sample-customers",
            "sample-characteristics",
            "technical-users",
            "departments",
            "groups",
        )
    ),
    *(f"licenses/reference-data/{key}" for key in ("vendors", "products", "types", "categories", "restrictions")),
    *(f"locations/reference-data/{key}" for key in ("countries", "cities", "buildings", "station-types")),
    "bench-bookings/reference-data/projects",
    "benches/reference-data/groups",
    "benches/reference-data/types",
]


@pytest.fixture
def importer(db):
    return get_user_model().objects.create(username="synthetic-importer", is_superuser=True, is_staff=True)


@pytest.fixture
def client(importer):
    result = APIClient()
    grant_labs_role(importer, "coord")
    result.force_authenticate(importer)
    return result


@pytest.mark.django_db
@pytest.mark.parametrize("catalog", PATHS)
def test_catalog_list_detail_and_authentication(client, catalog):
    url = ROOT + catalog
    response = client.get(url)
    assert response.status_code == 200, response.data
    assert isinstance(response.data["data"], list)
    assert "pagination" in response.data["meta"]
    assert client.get(url + "/999999999").status_code == 404
    assert client.get(url, {"unknown": "1"}).status_code == 400
    assert APIClient().get(url).status_code in (401, 403)
    view = getattr(resolve(url).func, "view_class")
    if catalog in READ_ONLY_PATHS:
        assert not hasattr(view, "post_contract")
        assert not hasattr(view, "handle_post")
    else:
        assert view.post_contract.request is not None


@pytest.mark.django_db
def test_create_retrieve_replay_and_mismatched_key(client):
    url = ROOT + "equipment/reference-data/departments"
    payload = {"name": "Synthetic department", "description": "Import test"}
    first = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="row-1")
    assert first.status_code == 201, first.data
    second = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="row-1")
    assert second.status_code == 201, second.data
    assert second.data == first.data
    assert second["Idempotency-Replayed"] == "true"
    assert client.get(first["Location"]).data == first.data
    mismatch = client.post(url, {"name": "Different"}, format="json", HTTP_IDEMPOTENCY_KEY="row-1")
    assert mismatch.status_code == 422
    assert mismatch.data["error"]["code"] == "idempotency_key_reuse"
    assert Department.objects.filter(name=payload["name"]).count() == 1
    assert ReferenceImportReceipt.objects.count() == 1


@pytest.mark.django_db
def test_permissions_input_and_foreign_keys(client):
    url = ROOT + "equipment/reference-data/departments"
    reader = get_user_model().objects.create(username="synthetic-no-permissions")
    grant_labs_role(reader, "user")  # plain Labs users may not import reference data
    client.force_authenticate(reader)
    denied = client.post(url, {"name": "Denied"}, format="json", HTTP_IDEMPOTENCY_KEY="denied")
    assert denied.status_code == 403, denied.data
    assert not Department.objects.filter(name="Denied").exists()
    client.force_authenticate(
        user=grant_labs_role(get_user_model().objects.get(username="synthetic-importer"), "coord")
    )
    for payload in ({"name": "Valid", "creator": 1}, {"name": ""}, {"name": 123}):
        assert client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="invalid").status_code == 422
    assert client.post(url, {"name": "No key"}, format="json").status_code == 422
    missing = client.post(
        ROOT + "equipment/reference-data/kinds",
        {"name": "Missing", "category_id": 99999999},
        format="json",
        HTTP_IDEMPOTENCY_KEY="missing-fk",
    )
    assert missing.status_code == 422, missing.data
    assert not EquipmentKind.objects.filter(name="Missing").exists()


@pytest.mark.django_db
def test_equipment_parent_validation_and_many_to_many(client):
    category = EquipmentCategory.objects.create(
        name="Synthetic inactive", key="synthetic-inactive", definition="Test", active=False
    )
    response = client.post(
        ROOT + "equipment/reference-data/kinds",
        {"name": "Invalid active kind", "category_id": category.pk},
        format="json",
        HTTP_IDEMPOTENCY_KEY="inactive",
    )
    assert response.status_code == 422, response.data
    manufacturer = client.post(
        ROOT + "equipment/reference-data/manufacturers",
        {"name": "Synthetic manufacturer", "category_ids": [category.pk]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="manufacturer",
    )
    assert manufacturer.status_code == 201, manufacturer.data
    assert manufacturer.data["data"]["category_ids"] == [category.pk]


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_replays_one_record():
    actor = get_user_model().objects.create(username="synthetic-concurrent", is_superuser=True)
    resource = ReferenceResource("test-department", Department, ("name",), ("name",))
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            local_actor = get_user_model().objects.get(pk=actor.pk)
            barrier.wait(timeout=10)
            return create_reference(
                resource, CreateReferenceInput({"name": "Concurrent"}, "one-key"), actor=local_actor
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(result.replayed for result in results) == 1
    assert results[0].data == results[1].data
    assert Department.objects.filter(name="Concurrent").count() == 1


@pytest.mark.django_db
def test_create_and_retrieve_every_reference_type(client):
    """Breaks if any registry field, parent relation or output projection is wrong."""
    importer = get_user_model().objects.get(username="synthetic-importer")
    reader = get_user_model().objects.create(username="synthetic-catalog-reader")
    # Equipment categories are provisioned defaults: readable, not importable.
    category = EquipmentCategory.objects.create(name="Synthetic category", key="synthetic", definition="Test")
    ids: dict[str, int] = {"categories": category.pk}
    payloads: list[tuple[str, dict[str, Any]]] = [
        ("equipment/reference-data/kinds", {"name": "Synthetic kind", "category_id": "categories"}),
        ("equipment/reference-data/types", {"name": "Synthetic type", "kind_id": "kinds"}),
        ("equipment/reference-data/manufacturers", {"name": "Synthetic maker", "category_ids": ["categories"]}),
        (
            "equipment/reference-data/product-models",
            {"name": "Synthetic model", "manufacturer_id": "manufacturers", "equipment_type_id": "types"},
        ),
        (
            "equipment/reference-data/specification-definitions",
            {"name": "Voltage", "value_type": "number", "unit": "V"},
        ),
        (
            "equipment/reference-data/product-model-specifications",
            {"product_model_id": "product-models", "definition_id": "specification-definitions", "value": "12.5"},
        ),
        ("equipment/reference-data/interfaces", {"name": "Synthetic interface"}),
        ("equipment/reference-data/materials", {"name": "Synthetic material"}),
        ("equipment/reference-data/display-sizes", {"size": "Synthetic size", "diagonal_in": "27.0"}),
        (
            "equipment/reference-data/display-resolutions",
            {"resolution": "Synthetic resolution", "width_px": 1920, "height_px": 1080},
        ),
        ("equipment/reference-data/networking-protocols", {"name": "Synthetic protocol"}),
        ("equipment/reference-data/sample-customers", {"name": "Synthetic customer"}),
        ("equipment/reference-data/sample-characteristics", {"name": "Synthetic characteristic"}),
        ("equipment/reference-data/technical-users", {"username": "synthetic-service-account"}),
        ("equipment/reference-data/departments", {"name": "Synthetic department"}),
        (
            "equipment/reference-data/groups",
            {"name": "Synthetic group", "department_id": "departments"},
        ),
        ("licenses/reference-data/vendors", {"name": "Synthetic vendor"}),
        ("licenses/reference-data/products", {"name": "Synthetic product", "vendor_id": "vendors"}),
        ("licenses/reference-data/types", {"name": "Synthetic license type"}),
        ("licenses/reference-data/categories", {"name": "Synthetic license category"}),
        ("licenses/reference-data/restrictions", {"name": "Synthetic restriction"}),
        ("locations/reference-data/countries", {"name": "Synthetic country", "code": "ZZ"}),
        ("locations/reference-data/cities", {"name": "Synthetic city", "country_id": "countries"}),
        (
            "locations/reference-data/buildings",
            {"name": "Synthetic building", "city_id": "cities", "address": "Synthetic address"},
        ),
        ("locations/reference-data/station-types", {"name": "Synthetic station type"}),
        ("bench-bookings/reference-data/projects", {"project_name": "Synthetic project", "code": "SYN-1"}),
        ("benches/reference-data/groups", {"name": "Synthetic bench group"}),
        ("benches/reference-data/types", {"name": "Synthetic bench type"}),
    ]
    for index, (catalog, payload) in enumerate(payloads):
        for field, value in list(payload.items()):
            if field.endswith("_id"):
                payload[field] = ids[value]
            elif isinstance(value, list):
                payload[field] = [ids[item] for item in value]
        response = client.post(ROOT + catalog, payload, format="json", HTTP_IDEMPOTENCY_KEY=f"import-{index}")
        assert response.status_code == 201, (catalog, response.data)
        ids[catalog.rsplit("/", 1)[1]] = response.data["data"]["id"]
        assert client.get(response["Location"]).data == response.data, catalog
        replay = client.post(ROOT + catalog, payload, format="json", HTTP_IDEMPOTENCY_KEY=f"import-{index}")
        assert replay.status_code == 201, (catalog, replay.data)
        assert replay.data == response.data
        assert replay["Idempotency-Replayed"] == "true"
        grant_labs_role(reader, "user")  # can read catalogs through the dashboard, may not import
        client.force_authenticate(reader)
        denied = client.post(ROOT + catalog, payload, format="json", HTTP_IDEMPOTENCY_KEY=f"denied-{index}")
        assert denied.status_code == 403, (catalog, denied.data)
        grant_labs_role(importer, "coord")
        client.force_authenticate(importer)


@pytest.mark.django_db
def test_equipment_categories_are_read_only_through_the_import_api(client):
    """Categories come from provisioned defaults; the catalog lists and retrieves but never creates."""
    category = EquipmentCategory.objects.create(name="Provisioned", key="provisioned", definition="Default")
    url = ROOT + "equipment/reference-data/categories"

    created = client.post(
        url,
        {"name": "Imported", "key": "imported", "definition": "Not allowed"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="category-import",
    )
    listed = client.get(url)
    detail = client.get(f"{url}/{category.pk}")

    assert created.status_code == 405
    assert "POST" not in created["Allow"]
    assert not EquipmentCategory.objects.filter(key="imported").exists()
    assert not ReferenceImportReceipt.objects.exists()
    assert listed.status_code == 200
    assert [row["key"] for row in listed.data["data"]] == ["provisioned"]
    assert detail.status_code == 200
    assert detail.data["data"]["id"] == category.pk


@pytest.mark.django_db
def test_lab_role_decides_reference_imports_not_django_permissions(client):
    """Labs reference data follows Labs roles, not Django add_ permissions.

    Equipment reference data needs the Labs admin role (owner decision 2026-11-10); the other Labs
    catalogs need a lab coordinator or admin (owner decision 2026-11-12).
    """
    from django.contrib.auth.models import Permission

    coordinator = grant_labs_role(get_user_model().objects.create(username="synthetic-coordinator"), "coord")
    client.force_authenticate(coordinator)
    created = client.post(
        ROOT + "licenses/reference-data/vendors",
        {"name": "Coordinator vendor"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="coordinator",
    )
    assert created.status_code == 201, created.data
    equipment_denied = client.post(
        ROOT + "equipment/reference-data/materials",
        {"name": "Coordinator material"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="coordinator-equipment",
    )
    assert equipment_denied.status_code == 403

    scoped = get_user_model().objects.create(username="synthetic-scoped-importer")
    scoped.user_permissions.add(Permission.objects.get(content_type__app_label="labs", codename="add_licensetype"))
    grant_labs_role(scoped, "user")
    client.force_authenticate(scoped)
    denied = client.post(
        ROOT + "licenses/reference-data/types",
        {"name": "Not permitted"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="scoped",
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_invalid_project_dates_and_duplicate_rollback(client):
    url = ROOT + "bench-bookings/reference-data/projects"
    bad = client.post(
        url,
        {"project_name": "Invalid period", "start_date": "2026-12-02", "end_date": "2026-12-01"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="invalid-dates",
    )
    assert bad.status_code == 422, bad.data
    assert not ReferenceImportReceipt.objects.filter(key="invalid-dates").exists()
    data = {"project_name": "Repeated project"}
    assert client.post(url, data, format="json", HTTP_IDEMPOTENCY_KEY="first-project").status_code == 201
    duplicate = client.post(url, data, format="json", HTTP_IDEMPOTENCY_KEY="second-project")
    assert duplicate.status_code == 409, duplicate.data
    assert not ReferenceImportReceipt.objects.filter(key="second-project").exists()


@pytest.mark.django_db
def test_reference_query_budgets(client, django_assert_num_queries):
    """The list/detail budgets must not grow with record count."""
    for index in range(3):
        Department.objects.create(name=f"Query budget {index}")
    from core.reference_data.queries import get_reference, list_references

    actor = get_user_model().objects.get(username="synthetic-importer")
    resource = ReferenceResource("budget", Department, ("name",), ("name",))
    with django_assert_num_queries(1):
        rows = list(list_references(resource, actor=actor, filters={})[:25])
    with django_assert_num_queries(1):
        assert get_reference(resource, actor=actor, reference_id=rows[0].pk).pk == rows[0].pk
    with django_assert_num_queries(2):
        assert client.get(ROOT + "equipment/reference-data/departments").status_code == 200
    with django_assert_num_queries(1):
        assert client.get(ROOT + f"equipment/reference-data/departments/{rows[0].pk}").status_code == 200
