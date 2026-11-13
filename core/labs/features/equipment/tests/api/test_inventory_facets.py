"""Inventory facets must describe precisely the corresponding filtered list."""

from collections import Counter
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient
from rest_framework_api_key.models import APIKey

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import (
    Bench,
    Equipment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
)
from core.labs.models.resource.base.resource import Department, Group
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from tests.factories import set_condition

BASE = "/api/labs/equipment"
DIMENSIONS = ("category", "kind", "type", "manufacturer", "product_model_id", "department_id", "group_id")


@pytest.fixture
def inventory(db):
    actor = get_user_model().objects.create_user(username="facets_actor", email="facets@example.invalid")
    grant_labs_role(actor, "coord")  # equipment is visible to coordinators only (R4)
    client = APIClient()
    client.force_authenticate(actor)
    categories = [
        EquipmentCategory.objects.create(name=name, key=name.lower(), definition=f"Synthetic {name}")
        for name in ("Computing", "Display")
    ]
    kinds = [
        EquipmentKind.objects.create(category=category, name=f"Facet kind {i}")
        for i, category in enumerate(categories)
    ]
    types = [EquipmentType.objects.create(kind=kind, name=f"Facet type {i}") for i, kind in enumerate(kinds)]
    makers = [EquipmentManufacturer.objects.create(name=f"Facet maker {i}") for i in range(2)]
    for category, maker in zip(categories, makers, strict=True):
        category.manufacturers.add(maker)
    models = [
        EquipmentProductModel.objects.create(name=f"Facet model {i}", equipment_type=types[i], manufacturer=makers[i])
        for i in range(2)
    ]
    departments = [Department.objects.create(name=f"Facet department {i}") for i in range(2)]
    groups = [Group.objects.create(name=f"Facet group {i}", department=departments[i]) for i in range(2)]
    rows = []
    for i in range(3):
        index = 0 if i < 2 else 1
        rows.append(
            Equipment.objects.create(
                sku=f"FACET-{i}",
                name=f"Facet inventory {i}",
                kind=kinds[index],
                type=types[index],
                manufacturer=makers[index],
                product_model=models[index],
                department=departments[index],
                group=groups[index],
            )
        )
    Equipment.objects.create(sku="FACET-NULL", name="Null inventory", kind=kinds[0])
    Equipment.objects.create(
        sku="FACET-DELETED", name="Deleted inventory", kind=kinds[0], type=types[0], deleted_at=timezone.now()
    )
    return client, categories, kinds, types, makers, models, departments, groups, rows


@pytest.mark.django_db
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_counts_match_filtered_inventory(inventory, dimension):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    response = client.get(
        f"{BASE}/facets",
        {"dimension": dimension, "category": categories[0].pk, "q": "Facet inventory", "page_size": 1},
    )
    assert response.status_code == 200
    assert len(response.data["data"]) == 1
    assert response.data["data"][0]["equipment_count"] == 2
    listed = client.get(BASE, {"category": categories[0].pk, "q": "Facet inventory", "page_size": 1})
    assert listed.data["meta"]["pagination"]["count"] == 2
    assert response.data["meta"]["pagination"]["count"] == 1


@pytest.mark.django_db
def test_taxonomy_and_organization_dependencies(inventory):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    selections = {
        "category": categories[0].pk,
        "kind": kinds[0].pk,
        "type": types[0].pk,
        "manufacturer": makers[0].pk,
        "product_model_id": models[0].pk,
        "department_id": departments[0].pk,
        "group_id": groups[0].pk,
    }
    for dimension in DIMENSIONS:
        response = client.get(f"{BASE}/facets", {**selections, "dimension": dimension})
        assert response.status_code == 200
        assert response.data["data"][0]["value"]["id"] == selections[dimension]
        assert response.data["data"][0]["equipment_count"] == 2
    for incompatible in (
        {"kind": kinds[1].pk},
        {"type": types[1].pk},
        {"manufacturer": makers[1].pk},
        {"product_model_id": models[1].pk},
        {"department_id": departments[1].pk},
        {"group_id": groups[1].pk},
    ):
        response = client.get(f"{BASE}/facets", {**selections, **incompatible, "dimension": "group_id"})
        assert response.status_code == 200
        assert response.data["data"] == []
    combined = client.get(
        f"{BASE}/facets",
        {"dimension": "category", "category": f"{categories[0].pk},{categories[1].pk}", "q": "Facet inventory"},
    )
    assert [row["equipment_count"] for row in combined.data["data"]] == [2, 1]
    for path in (BASE,):
        listed = client.get(path, {"department_id": departments[0].pk, "product_model_id": models[0].pk})
        assert listed.status_code == 200
        assert {row["id"] for row in listed.data["data"]} == {rows[0].pk, rows[1].pk}


@pytest.mark.django_db
def test_null_retired_buckets_pagination_and_unknown_ids(inventory):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    EquipmentManufacturer.objects.filter(pk=makers[0].pk).update(active=False)
    EquipmentCategory.objects.filter(pk=categories[0].pk).update(active=False)
    response = client.get(f"{BASE}/facets", {"dimension": "manufacturer", "page_size": 1})
    assert response.status_code == 200
    assert response.data["data"] == [{"value": {"id": makers[0].pk, "name": makers[0].name}, "equipment_count": 2}]
    assert response.data["meta"]["pagination"]["count"] == 3
    assert "dimension=manufacturer" in response.data["meta"]["pagination"]["next"]
    last = client.get(f"{BASE}/facets", {"dimension": "manufacturer", "page_size": 1, "page": 3})
    assert last.data["data"] == [{"value": None, "equipment_count": 1}]
    missing = client.get(f"{BASE}/facets", {"dimension": "type", "type": "999999"})
    assert missing.status_code == 200 and missing.data["data"] == []
    default = client.get(f"{BASE}/facets", {"dimension": "category"})
    assert default.data["meta"]["pagination"]["page_size"] == 25


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        {},
        {"dimension": "owner_id"},
        {"dimension": "kind__category"},
        {"dimension": ""},
        {"dimension": "kind", "ordering": "name"},
        {"dimension": "kind", "include_ids": "1"},
        {"dimension": "kind", "unexpected": "1"},
        {"dimension": "kind", "page_size": 101},
        {"dimension": "kind", "page": 0},
        {"dimension": "kind", "department_id": ""},
        {"dimension": "kind", "product_model_id": "1,1"},
        {"dimension": "kind", "department_id": "1,,2"},
        {"dimension": "kind", "department_id": "01"},
        {"dimension": "kind", "product_model_id": "-1"},
        {"dimension": "kind", "product_model_id": "1, 2"},
        {"dimension": "kind", "department_id": "x"},
        {"dimension": "kind", "department_id": ",".join(str(i) for i in range(1, 52))},
    ],
)
def test_invalid_queries(inventory, query):
    client = inventory[0]
    for path in (f"{BASE}/facets",):
        response = client.get(path, query)
        assert response.status_code == 400
        assert response.data["error"]["code"] == "invalid_query"
        assert response.data["error"]["details"]


@pytest.mark.django_db
def test_repeated_parameters_and_search_parity(inventory):
    client = inventory[0]
    repeated = client.get(f"{BASE}/facets?dimension=kind&dimension=type")
    assert repeated.status_code == 400 and repeated.data["error"]["code"] == "invalid_query"
    for path, search in ((BASE, "Facet maker 0"), (BASE, "FACET-0")):
        for alias in ("q", "search"):
            listed = client.get(path, {alias: search})
            facets = client.get(f"{path}/facets", {"dimension": "kind", alias: search})
            assert facets.status_code == 200
            assert (
                sum(row["equipment_count"] for row in facets.data["data"])
                == listed.data["meta"]["pagination"]["count"]
            )


@pytest.mark.django_db
def test_runtime_category_lists_and_facets_through_the_single_collection(inventory):
    """A category created at runtime needs no model or route: filter the one collection (AC7)."""
    client = inventory[0]
    catalog = EquipmentCategory.objects.create(name="Adapter runtime", key="adapter-runtime", definition="Runtime")
    kind = EquipmentKind.objects.create(category=catalog, name="Adapter runtime kind")
    record = Equipment.objects.create(sku="ADAPTER-RUNTIME", name="Adapter runtime inventory", kind=kind)
    listed = client.get(BASE, {"category": catalog.pk})
    facets = client.get(f"{BASE}/facets", {"dimension": "category", "category": catalog.pk})
    assert listed.status_code == facets.status_code == 200
    assert {row["id"] for row in listed.data["data"]} == {record.pk}
    assert facets.data["data"] == [{"value": {"id": catalog.pk, "name": catalog.name}, "equipment_count": 1}]
    assert client.get(f"{BASE}/adapter-runtime").status_code == 404


@pytest.mark.django_db
def test_authorization(inventory):
    client = APIClient()
    for path in (f"{BASE}/facets",):
        denied = client.get(path, {"dimension": "kind"})
        assert denied.status_code == 401
        assert "error" in denied.data and "data" not in denied.data
    key_record, key = APIKey.objects.create_key(name="synthetic-facet-test")
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    for path in (f"{BASE}/facets",):
        assert client.get(path, {"dimension": "kind"}).status_code == 200
    key_record.revoked = True
    key_record.save()
    assert client.get(f"{BASE}/facets", {"dimension": "kind"}).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("path", (BASE,))
def test_bounded_queries(inventory, django_assert_num_queries, path):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    for i in range(3):
        Equipment.objects.create(
            sku=f"BUDGET-{i}",
            name=f"Budget {i}",
            kind=kinds[0],
            manufacturer=makers[0],
            department=departments[0],
            group=groups[0],
        )
    # Warm permission and content-type machinery before measuring database reads.
    client.get(f"{path}/facets", {"dimension": "manufacturer"})
    with django_assert_num_queries(2):
        response = client.get(f"{path}/facets", {"dimension": "manufacturer"})
        assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("path", (BASE,))
@pytest.mark.parametrize("parameter", ("page", "page_size"))
def test_oversized_decimal_pagination_is_400_before_inventory_sql(
    inventory, django_assert_num_queries, path, parameter
):
    # Reads are role-checked; resolve the actor's roles first (cached on the user) so the count
    # below measures only the endpoint's own queries.
    inventory[0].get(f"{path}/facets", {"dimension": "kind"})  # warm
    with django_assert_num_queries(0):
        response = inventory[0].get(f"{path}/facets", {"dimension": "kind", parameter: "9" * 5000})
    assert response.status_code == 400
    assert response.data["error"]["code"] == "invalid_query"
    assert response.data["error"]["details"][0]["field"] == parameter


@pytest.mark.parametrize("custom_header", (None, "HTTP_X_API_KEY"))
def test_all_facet_operations_document_pagination_and_api_key(custom_header):
    from core.labs.features.equipment.api.urls import urlpatterns

    with override_settings(API_KEY_CUSTOM_HEADER=custom_header):
        schema = SchemaGenerator(patterns=urlpatterns).get_schema(public=True)
    operations = [item["get"] for path, item in schema["paths"].items() if path.endswith("/facets")]
    assert len(operations) == 1
    for operation in operations:
        parameters = {item["name"]: item for item in operation["parameters"]}
        assert parameters["dimension"]["required"] is True
        for name, default in (("page", 1), ("page_size", 25)):
            assert parameters[name]["in"] == "query"
            assert not parameters[name].get("required", False)
            assert parameters[name]["schema"]["type"] == "integer"
            assert parameters[name]["schema"]["minimum"] == 1
            assert parameters[name]["schema"]["default"] == default
        assert parameters["page_size"]["schema"]["maximum"] == 100
        assert {"equipmentFacetsApiKey": []} in operation["security"]
        assert {} not in operation["security"]
    scheme = schema["components"]["securitySchemes"]["equipmentFacetsApiKey"]
    assert scheme["type"] == "apiKey" and scheme["in"] == "header"
    assert scheme["name"] == ("X-API-KEY" if custom_header else "Authorization")
    if not custom_header:
        assert "Api-Key <key>" in scheme["description"]


@pytest.mark.django_db
def test_pagination_controls_are_not_membership_filters(inventory, monkeypatch):
    from core.common.api.filtering import FilterSpec

    original = FilterSpec.apply

    def apply(spec, population, values):
        assert not {"page", "page_size", "dimension"}.intersection(values)
        return original(spec, population, values)

    monkeypatch.setattr(FilterSpec, "apply", apply)
    for path in (BASE,):
        for query in ({}, {"page": 1, "page_size": 100}):
            assert inventory[0].get(f"{path}/facets", {"dimension": "kind", **query}).status_code == 200


def assert_bucket_parity(client, path, query, dimension, expected_ids):
    """Check exact list membership and per-value counts, not just total equality."""
    listed = client.get(path, {**query, "page_size": 100})
    assert listed.status_code == 200
    assert {row["id"] for row in listed.data["data"]} == set(expected_ids)
    facets = client.get(f"{path}/facets", {**query, "dimension": dimension, "page_size": 100})
    assert facets.status_code == 200
    lookup = {
        "category": "kind__category_id",
        "kind": "kind_id",
        "type": "type_id",
        "manufacturer": "manufacturer_id",
        "product_model_id": "product_model_id",
        "department_id": "department_id",
        "group_id": "group_id",
    }[dimension]
    expected = Counter(Equipment.objects.filter(pk__in=expected_ids).values_list(lookup, flat=True))
    actual = {row["value"]["id"] if row["value"] else None: row["equipment_count"] for row in facets.data["data"]}
    assert actual == expected


@pytest.mark.django_db
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_individual_csv_or_on_every_dimension(inventory, dimension):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    references = dict(zip(DIMENSIONS, (categories, kinds, types, makers, models, departments, groups), strict=True))
    query = {dimension: ",".join(str(item.pk) for item in references[dimension]), "q": "Facet inventory"}
    assert_bucket_parity(client, BASE, query, dimension, [row.pk for row in rows])
    assert_bucket_parity(
        client, BASE, {**query, dimension: references[dimension][0].pk}, dimension, [row.pk for row in rows[:2]]
    )


@pytest.mark.django_db
def test_parent_only_siblings_crossed_relationships_and_csv_conjunction(inventory):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    sibling_kind = EquipmentKind.objects.create(category=categories[0], name="Sibling kind")
    sibling_type = EquipmentType.objects.create(kind=sibling_kind, name="Sibling type")
    sibling_group = Group.objects.create(department=departments[0], name="Sibling group")
    categories[0].manufacturers.add(makers[1])
    sibling_model = EquipmentProductModel.objects.create(
        name="Sibling model", equipment_type=sibling_type, manufacturer=makers[1]
    )
    sibling = Equipment.objects.create(
        sku="PARENT-SIBLING",
        name="Parent inventory sibling",
        kind=sibling_kind,
        type=sibling_type,
        manufacturer=makers[1],
        product_model=sibling_model,
        department=departments[0],
        group=sibling_group,
    )
    crossed = Equipment.objects.create(
        sku="PARENT-CROSSED",
        name="Parent inventory crossed",
        kind=kinds[1],
        type=types[1],
        manufacturer=makers[1],
        product_model=models[1],
        department=departments[1],
        group=groups[1],
    )
    Equipment.objects.filter(pk=crossed.pk).update(kind=kinds[0], department=departments[0])
    # Historical crossed FK values are intentional: facets mirror stored list
    # membership rather than silently imposing catalog eligibility joins.
    selected = [rows[0].pk, rows[1].pk, sibling.pk, crossed.pk]
    for dimension in ("kind", "type", "manufacturer", "product_model_id"):
        assert_bucket_parity(
            client,
            BASE,
            {"category": categories[0].pk},
            dimension,
            selected + [Equipment.objects.get(sku="FACET-NULL").pk],
        )
    for parent, dimension, ids in (
        (
            {"kind": kinds[0].pk, "q": "inventory"},
            "type",
            [rows[0].pk, rows[1].pk, crossed.pk, Equipment.objects.get(sku="FACET-NULL").pk],
        ),
        ({"type": types[1].pk}, "product_model_id", [rows[2].pk, crossed.pk]),
        ({"manufacturer": makers[1].pk}, "product_model_id", [rows[2].pk, sibling.pk, crossed.pk]),
        ({"department_id": departments[0].pk}, "group_id", selected),
    ):
        assert_bucket_parity(client, BASE, parent, dimension, ids)
    query = {"category": f"{categories[0].pk},{categories[1].pk}", "group_id": f"{groups[0].pk},{sibling_group.pk}"}
    assert_bucket_parity(client, BASE, query, "type", [rows[0].pk, rows[1].pk, sibling.pk])
    assert_bucket_parity(client, BASE, {**query, "type": types[1].pk}, "type", [])


@pytest.mark.django_db
@pytest.mark.parametrize("path", (BASE,))
@pytest.mark.parametrize("filter_name", ("status", "assigned", "owner", "date", "combined"))
def test_inherited_filters_exact_bucket_parity(inventory, path, filter_name):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    now = timezone.now()
    actor = get_user_model().objects.get(username="facets_actor")
    Equipment.objects.filter(pk=rows[0].pk).update(owner=actor, created=now - timedelta(days=1))
    Equipment.objects.filter(pk__in=[rows[1].pk, rows[2].pk]).update(created=now - timedelta(days=3))
    # rows[0] is on a bench (display_status in_use); rows[1] is out of service (broken).
    set_condition(rows[1], "out_of_service")
    bench = Bench.objects.create(sku="FACET-BENCH", name="Synthetic facet bench")
    EquipmentAssignment.objects.create(equipment=rows[0], bench=bench, assigned_at=now)
    EquipmentAssignment.objects.create(
        equipment=rows[1], bench=bench, assigned_at=now - timedelta(days=2), unassigned_at=now
    )
    queries: dict[str, dict[str, Any]] = {
        "status": {"status": "in_use"},
        "assigned": {"assigned": "true"},
        "owner": {"owner_id": actor.pk},
        "date": {"created_at_after": (now - timedelta(days=2)).isoformat(), "created_at_before": now.isoformat()},
    }
    query = (
        {**queries["status"], **queries["assigned"], **queries["owner"], **queries["date"]}
        if filter_name == "combined"
        else queries[filter_name]
    )
    assert_bucket_parity(client, path, {**query, "q": "Facet inventory"}, "type", [rows[0].pk])
    if filter_name == "assigned":
        expected = [rows[1].pk, rows[2].pk]
        assert_bucket_parity(client, path, {"assigned": "false", "q": "Facet inventory"}, "type", expected)


@pytest.mark.django_db
def test_category_subtype_filter_bucket_parity(inventory):
    from core.labs.models.resource.equipment import DisplaySize

    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    size = DisplaySize.objects.create(size="Facet 24 inch")
    Equipment.objects.filter(pk=rows[2].pk).update(size=size)
    Equipment.objects.create(sku="SUBTYPE-OTHER", name="Other display", kind=kinds[1])
    assert_bucket_parity(client, BASE, {"size_id": size.pk}, "kind", [rows[2].pk])


@pytest.mark.django_db
def test_maximum_page_size_duplicate_names_and_links(inventory):
    client, categories, kinds, types, makers, models, departments, groups, rows = inventory
    first = EquipmentType.objects.create(kind=kinds[0], name="Duplicate")
    second = EquipmentType.objects.create(kind=kinds[1], name="Duplicate")
    Equipment.objects.create(sku="DUP-FIRST", name="Duplicate inventory", kind=kinds[0], type=first)
    Equipment.objects.create(sku="DUP-SECOND", name="Duplicate inventory", kind=kinds[1], type=second)
    for page, expected in ((1, first.pk), (2, second.pk)):
        response = client.get(
            f"{BASE}/facets", {"dimension": "type", "q": "Duplicate inventory", "page_size": 1, "page": page}
        )
        assert response.status_code == 200
        assert response.data["data"][0]["value"]["id"] == expected
        pagination = response.data["meta"]["pagination"]
        link = pagination["next" if page == 1 else "previous"]
        params = parse_qs(urlsplit(link).query)
        assert params["dimension"] == ["type"] and params["q"] == ["Duplicate inventory"]
        assert params["page_size"] == ["1"]
        assert client.get(link).data["data"][0]["value"]["id"] == (second.pk if page == 1 else first.pk)
    response = client.get(f"{BASE}/facets", {"dimension": "type", "page_size": 100})
    assert response.status_code == 200
    assert response.data["meta"]["pagination"]["page_size"] == 100
