"""Behavioral tests for equipment options and category options endpoints (ADR 002)."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.models import Bench
from core.labs.models.resource.base.resource import Department, ResourceGroup
from core.labs.models.resource.equipment.assignment import EquipmentAssignment
from core.labs.models.resource.equipment.computing import ComputingEquipment, TechnicalUser
from core.labs.models.resource.equipment.display import DisplayEquipment
from core.labs.models.resource.equipment.equipment import EquipmentStatus, EquipmentStatusRecord
from core.labs.models.resource.equipment.reference_data import (
    EquipmentCategory,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
)
from tests.factories import grant_labs_role


@pytest.fixture()
def api_client():
    return APIClient()


@pytest.fixture()
def actor(db):
    User = get_user_model()
    return grant_labs_role(User.objects.create_user(username="options_actor", email="options@example.com"), "coord")


@pytest.fixture()
def computing_category(db):
    category = EquipmentCategory.objects.create(name="Computing", key="computing", definition="Computing equipment")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    return category, kind


@pytest.fixture()
def display_category(db):
    category = EquipmentCategory.objects.create(name="Display", key="display", definition="Display equipment")
    kind = EquipmentKind.objects.create(category=category, name="Monitor")
    return category, kind


@pytest.fixture()
def bench(db):
    return Bench.objects.create(name="Bench 1", sku="BENCH-OPT-01")


def _set_status(equipment, status_value, actor):
    return EquipmentStatusRecord.objects.create(
        equipment=equipment,
        status=status_value,
        metadata={"note": "Test status"},
        creator=actor,
        last_modified_by=actor,
    )


@pytest.mark.django_db
def test_unauthenticated_options_rejected(api_client):
    assert api_client.get("/api/labs/equipment/options", {"q": "Laptop"}).status_code == status.HTTP_401_UNAUTHORIZED
    assert api_client.get("/api/labs/equipment/computing/reference-data").status_code == status.HTTP_401_UNAUTHORIZED
    assert (
        api_client.get("/api/labs/equipment/computing/options", {"q": "PC"}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "allowed_narrowing"),
    (
        (
            "/api/labs/equipment/options",
            (
                "category_id",
                "kind_id",
                "type_id",
                "manufacturer_id",
            ),
        ),
        (
            "/api/labs/equipment/computing/options",
            ("kind_id", "type_id", "manufacturer_id"),
        ),
        (
            "/api/labs/equipment/display/options",
            ("kind_id", "type_id", "manufacturer_id"),
        ),
        ("/api/labs/equipment-types/options", ("kind_id", "category_id")),
        ("/api/labs/equipment-manufacturers/options", ("category_id",)),
        ("/api/labs/equipment-product-models/options", ("manufacturer_id", "type_id")),
    ),
)
def test_large_equipment_options_require_adr_declared_narrowing(
    api_client,
    actor,
    path,
    allowed_narrowing,
    computing_category,
    display_category,
):
    api_client.force_authenticate(user=actor)
    computing, computing_kind = computing_category
    display, display_kind = display_category
    computing_type = EquipmentType.objects.create(kind=computing_kind, name="Workstation")
    display_type = EquipmentType.objects.create(kind=display_kind, name="Monitor")
    manufacturer = EquipmentManufacturer.objects.create(name="Selector Manufacturer")
    unrelated_manufacturer = EquipmentManufacturer.objects.create(name="Unrelated Manufacturer")
    computing.manufacturers.add(manufacturer)
    display.manufacturers.add(unrelated_manufacturer)
    product_model = EquipmentProductModel.objects.create(
        manufacturer=manufacturer,
        equipment_type=computing_type,
        name="Selector Workstation",
    )
    unrelated_product_model = EquipmentProductModel.objects.create(
        manufacturer=unrelated_manufacturer,
        equipment_type=display_type,
        name="Unrelated Monitor",
    )
    equipment = ComputingEquipment.objects.create(
        sku="SEL-COMPUTER",
        name="Selector Computer",
        kind=computing_kind,
        type=computing_type,
        manufacturer=manufacturer,
        product_model=product_model,
    )
    display_equipment = DisplayEquipment.objects.create(
        sku="SEL-DISPLAY",
        name="Selector Display",
        kind=display_kind,
        type=display_type,
        manufacturer=unrelated_manufacturer,
        product_model=unrelated_product_model,
    )
    _set_status(equipment, EquipmentStatus.AVAILABLE, actor)
    _set_status(display_equipment, EquipmentStatus.AVAILABLE, actor)

    filter_values = {
        "category_id": computing.pk,
        "kind_id": computing_kind.pk,
        "type_id": computing_type.pk,
        "manufacturer_id": manufacturer.pk,
    }
    if path == "/api/labs/equipment/display/options":
        filter_values["kind_id"] = display_kind.pk
        filter_values["type_id"] = display_type.pk
        filter_values["manufacturer_id"] = unrelated_manufacturer.pk
    missing = api_client.get(path)
    assert missing.status_code == status.HTTP_400_BAD_REQUEST
    assert missing.data["error"]["code"] == "invalid_query"

    for filter_name in allowed_narrowing:
        narrowed = api_client.get(path, {filter_name: filter_values[filter_name]})
        assert narrowed.status_code == status.HTTP_200_OK, filter_name
        if filter_name in {"category_id", "kind_id", "type_id", "manufacturer_id"}:
            result_ids = {item["id"] for item in narrowed.data["data"]}
            if path == "/api/labs/equipment/options":
                expected_ids = {equipment.pk}
            elif path == "/api/labs/equipment/computing/options":
                expected_ids = {equipment.pk}
            elif path == "/api/labs/equipment/display/options":
                expected_ids = {display_equipment.pk}
            elif path == "/api/labs/equipment-types/options":
                expected_ids = {computing_type.pk}
            elif path == "/api/labs/equipment-manufacturers/options":
                expected_ids = {manufacturer.pk}
            elif path == "/api/labs/equipment-product-models/options":
                expected_ids = {product_model.pk}
            else:
                pytest.fail(f"Unexpected equipment selector path: {path}")
            assert result_ids == expected_ids

    searched = api_client.get(path, {"q": "matching-none"})
    assert searched.status_code == status.HTTP_200_OK

    included = api_client.get(path, {"include_ids": "999999"})
    assert included.status_code == status.HTTP_400_BAD_REQUEST
    assert included.data["error"]["code"] == "invalid_query"

    included_with_search = api_client.get(path, {"q": "matching-none", "include_ids": "999999"})
    assert included_with_search.status_code == status.HTTP_200_OK

    if path in {"/api/labs/equipment/options", "/api/labs/equipment/computing/options"}:
        valid_nonmatching = api_client.get(path, {"q": "matching-none", "include_ids": str(equipment.pk)})
        assert valid_nonmatching.status_code == status.HTTP_200_OK
        assert [item["id"] for item in valid_nonmatching.data["data"]] == [equipment.pk]

        deleted = ComputingEquipment.objects.create(
            sku="SEL-DELETED",
            name="Deleted Selector Computer",
            kind=computing_kind,
            deleted_at=timezone.now(),
        )
        deleted_response = api_client.get(path, {"q": "matching-none", "include_ids": str(deleted.pk)})
        assert deleted_response.status_code == status.HTTP_200_OK
        assert deleted_response.data["data"] == []

    if path == "/api/labs/equipment/options":
        assigned_only = api_client.get(path, {"assigned": "true"})
        assert assigned_only.status_code == status.HTTP_400_BAD_REQUEST
        assert assigned_only.data["error"]["code"] == "invalid_query"


@pytest.mark.django_db
def test_equipment_options_assignable_true_ignores_bench_assigned_and_unavailable(
    api_client, actor, computing_category, bench
):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category

    # 1. Available and unassigned -> INCLUDED
    available_eq = ComputingEquipment.objects.create(sku="EQ-AVAIL", name="Available Laptop", kind=kind)
    _set_status(available_eq, EquipmentStatus.AVAILABLE, actor)

    # 2. Available status BUT actively assigned to a bench -> IGNORED (already assigned)
    assigned_eq = ComputingEquipment.objects.create(sku="EQ-ASSIGNED", name="Assigned Laptop", kind=kind)
    _set_status(assigned_eq, EquipmentStatus.AVAILABLE, actor)
    EquipmentAssignment.objects.create(
        equipment=assigned_eq,
        bench=bench,
        assigned_at=timezone.now(),
        creator=actor,
        last_modified_by=actor,
    )

    # 3. In-use unassigned -> IGNORED (not available)
    in_use_eq = ComputingEquipment.objects.create(sku="EQ-INUSE", name="In Use Laptop", kind=kind)
    _set_status(in_use_eq, EquipmentStatus.IN_USE, actor)

    # 4. Maintenance unassigned -> IGNORED (not available)
    maint_eq = ComputingEquipment.objects.create(sku="EQ-MAINT", name="Maintenance Laptop", kind=kind)
    _set_status(maint_eq, EquipmentStatus.MAINTENANCE, actor)

    # 5. Broken unassigned -> IGNORED (not available)
    broken_eq = ComputingEquipment.objects.create(sku="EQ-BROKEN", name="Broken Laptop", kind=kind)
    _set_status(broken_eq, EquipmentStatus.BROKEN, actor)

    # 6. Soft-deleted -> IGNORED
    deleted_eq = ComputingEquipment.objects.create(
        sku="EQ-DELETED", name="Deleted Laptop", kind=kind, deleted_at=timezone.now()
    )
    _set_status(deleted_eq, EquipmentStatus.AVAILABLE, actor)

    # Query with pattern options?assignable=true
    response = api_client.get("/api/labs/equipment/options", {"assignable": "true", "q": "Laptop"})
    assert response.status_code == status.HTTP_200_OK
    assert "ETag" in response.headers
    data = response.data["data"]
    ids = [item["id"] for item in data]

    assert available_eq.pk in ids
    assert assigned_eq.pk not in ids
    assert in_use_eq.pk not in ids
    assert maint_eq.pk not in ids
    assert broken_eq.pk not in ids
    assert deleted_eq.pk not in ids

    # Check item structure: clean, compact, strictly fixed keys { "id", "sku", "name" }
    item = next(i for i in data if i["id"] == available_eq.pk)
    assert item == {
        "id": available_eq.pk,
        "sku": "EQ-AVAIL",
        "name": "Available Laptop",
    }
    assert set(item.keys()) == {"id", "sku", "name"}


@pytest.mark.django_db
def test_slashless_options_route_standard(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category
    eq = ComputingEquipment.objects.create(sku="EQ-SLASH", name="Slash Test", kind=kind)
    _set_status(eq, EquipmentStatus.AVAILABLE, actor)

    resp_slashless = api_client.get("/api/labs/equipment/options", {"q": "Slash"})
    assert resp_slashless.status_code == status.HTTP_200_OK

    # Trailing slash route is removed per ADR 002
    resp_slash = api_client.get("/api/labs/equipment/options/", {"q": "Slash"})
    assert resp_slash.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_category_reference_data_follows_category_kind_type_manufacturer_model_hierarchy(
    api_client, actor, computing_category, display_category
):
    api_client.force_authenticate(user=actor)
    computing, computing_kind = computing_category
    display, display_kind = display_category

    computing_type = EquipmentType.objects.create(kind=computing_kind, name="Reference Compute Type")
    display_type = EquipmentType.objects.create(kind=display_kind, name="Reference Display Type")
    unassociated_type = EquipmentType.objects.create(kind=computing_kind, name="Unassociated Reference Type")

    computing_manufacturer = EquipmentManufacturer.objects.create(name="Computing Reference Maker")
    no_model_manufacturer = EquipmentManufacturer.objects.create(name="Computing Maker Without Model")
    display_manufacturer = EquipmentManufacturer.objects.create(name="Display Reference Maker")
    unassociated_manufacturer = EquipmentManufacturer.objects.create(name="Unassociated Reference Maker")
    computing.manufacturers.add(computing_manufacturer, no_model_manufacturer)
    display.manufacturers.add(display_manufacturer)

    computing_model = EquipmentProductModel.objects.create(
        manufacturer=computing_manufacturer,
        equipment_type=computing_type,
        name="Computing Reference Model",
    )
    display_model = EquipmentProductModel.objects.create(
        manufacturer=display_manufacturer,
        equipment_type=display_type,
        name="Display Reference Model",
    )
    # Removing a category association later leaves a previously valid model row.
    changed_manufacturer = EquipmentManufacturer.objects.create(name="M2M Changed Reference Maker")
    computing.manufacturers.add(changed_manufacturer)
    inconsistent_model = EquipmentProductModel.objects.create(
        manufacturer=changed_manufacturer,
        equipment_type=computing_type,
        name="Computing Model After M2M Change",
    )
    computing.manufacturers.remove(changed_manufacturer)
    display.manufacturers.add(changed_manufacturer)
    display_legacy_model = EquipmentProductModel.objects.create(
        manufacturer=changed_manufacturer,
        equipment_type=display_type,
        name="Display Model After M2M Change",
    )
    response = api_client.get("/api/labs/equipment/computing/reference-data")

    assert response.status_code == status.HTTP_200_OK
    data = response.data["data"]
    assert {row["id"] for row in data["kinds"]} == {computing_kind.pk}
    assert {row["id"] for row in data["types"]} == {computing_type.pk, unassociated_type.pk}
    assert {row["id"] for row in data["manufacturers"]} == {
        computing_manufacturer.pk,
        no_model_manufacturer.pk,
    }
    assert {row["id"] for row in data["product_models"]} == {computing_model.pk}
    assert display_kind.pk not in {row["id"] for row in data["kinds"]}
    assert display_type.pk not in {row["id"] for row in data["types"]}
    assert display_manufacturer.pk not in {row["id"] for row in data["manufacturers"]}
    assert display_model.pk not in {row["id"] for row in data["product_models"]}
    assert inconsistent_model.pk not in {row["id"] for row in data["product_models"]}
    assert unassociated_manufacturer.pk not in {row["id"] for row in data["manufacturers"]}
    assert unassociated_type.pk in {row["id"] for row in data["types"]}
    assert {"kinds", "types", "manufacturers", "product_models", "groups", "owners"} <= set(data)
    assert set(data["product_models"][0]) == {
        "id",
        "manufacturer",
        "name",
        "default_power_draw_w",
        "default_weight_kg",
        "specifications",
    }
    assert display_legacy_model.pk not in {row["id"] for row in data["product_models"]}


@pytest.mark.django_db
def test_category_reference_data_excludes_inactive_parents(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    category, kind = computing_category
    inactive_kind = EquipmentKind.objects.create(category=category, name="Inactive Reference Kind")
    inactive_kind_type = EquipmentType.objects.create(kind=inactive_kind, name="Inactive Kind Type")
    inactive_kind.active = False
    inactive_kind.save()
    inactive_type = EquipmentType.objects.create(kind=kind, name="Inactive Reference Type")
    manufacturer = EquipmentManufacturer.objects.create(name="Inactive Parent Manufacturer")
    category.manufacturers.add(manufacturer)
    inactive_manufacturer = EquipmentManufacturer.objects.create(name="Inactive Reference Manufacturer")
    category.manufacturers.add(inactive_manufacturer)
    inactive_manufacturer.active = False
    inactive_manufacturer.save()
    inactive_type.active = False
    inactive_type.save()
    response = api_client.get("/api/labs/equipment/computing/reference-data")

    assert response.status_code == status.HTTP_200_OK
    data = response.data["data"]
    assert inactive_kind.pk not in {row["id"] for row in data["kinds"]}
    assert inactive_type.pk not in {row["id"] for row in data["types"]}
    assert inactive_kind_type.pk not in {row["id"] for row in data["types"]}
    assert inactive_manufacturer.pk not in {row["id"] for row in data["manufacturers"]}

    inactive_model_manufacturer = EquipmentManufacturer.objects.create(name="Inactive Model Manufacturer")
    category.manufacturers.add(inactive_model_manufacturer)
    inactive_model = EquipmentProductModel.objects.create(
        manufacturer=inactive_model_manufacturer,
        equipment_type=EquipmentType.objects.create(kind=kind, name="Inactive Model Type"),
        name="Inactive Reference Product Model",
    )
    inactive_model_manufacturer.active = False
    inactive_model_manufacturer.save()
    inactive_model.active = False
    EquipmentProductModel.objects.filter(pk=inactive_model.pk).update(active=False)
    response = api_client.get("/api/labs/equipment/computing/reference-data")
    assert response.status_code == status.HTTP_200_OK
    assert inactive_model.pk not in {row["id"] for row in response.data["data"]["product_models"]}


@pytest.mark.django_db
def test_category_reference_data_excludes_inactive_category_descendants(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    category, kind = computing_category
    equipment_type = EquipmentType.objects.create(kind=kind, name="Inactive Category Type")
    manufacturer = EquipmentManufacturer.objects.create(name="Inactive Category Manufacturer")
    category.manufacturers.add(manufacturer)
    product_model = EquipmentProductModel.objects.create(
        manufacturer=manufacturer,
        equipment_type=equipment_type,
        name="Inactive Category Model",
    )
    EquipmentCategory.objects.filter(pk=category.pk).update(active=False)

    response = api_client.get("/api/labs/equipment/computing/reference-data")

    assert response.status_code == status.HTTP_200_OK
    data = response.data["data"]
    assert data["kinds"] == []
    assert data["types"] == []
    assert data["manufacturers"] == []
    assert data["product_models"] == []


@pytest.mark.django_db
def test_category_reference_data_preserves_groups_owners_and_category_lookups(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    category, _kind = computing_category
    group = ResourceGroup.objects.create(name="Reference Form Group")
    technical_user = TechnicalUser.objects.create(username="reference-tech")
    category.manufacturers.add(EquipmentManufacturer.objects.create(name="Lookup Preservation Maker"))

    response = api_client.get("/api/labs/equipment/computing/reference-data")

    assert response.status_code == status.HTTP_200_OK
    assert set(response.data["data"]) == {
        "kinds",
        "types",
        "manufacturers",
        "product_models",
        "groups",
        "owners",
        "technical_users",
    }
    data = response.data["data"]
    assert {row["id"] for row in data["groups"]} == {group.pk}
    assert {row["id"] for row in data["owners"]} == {actor.pk}
    assert {row["id"] for row in data["technical_users"]} == {technical_user.pk}


@pytest.mark.django_db
def test_generic_equipment_reference_data_keeps_cross_category_catalogs(api_client, actor, display_category):
    api_client.force_authenticate(user=actor)
    category, kind = display_category
    equipment_type = EquipmentType.objects.create(kind=kind, name="Generic Display Type")
    manufacturer = EquipmentManufacturer.objects.create(name="Generic Display Maker")
    category.manufacturers.add(manufacturer)
    product_model = EquipmentProductModel.objects.create(
        manufacturer=manufacturer,
        equipment_type=equipment_type,
        name="Generic Display Model",
    )

    response = api_client.get("/api/labs/equipment/reference-data")

    assert response.status_code == status.HTTP_200_OK
    data = response.data["data"]
    assert {row["name"] for row in data["categories"]} == {category.name}
    assert {row["id"] for row in data["kinds"]} == {kind.pk}
    assert {row["id"] for row in data["types"]} == {equipment_type.pk}
    assert {row["id"] for row in data["manufacturers"]} == {manufacturer.pk}
    assert {row["id"] for row in data["product_models"]} == {product_model.pk}


@pytest.mark.django_db
def test_category_reference_data_query_count_is_bounded(
    api_client, actor, computing_category, django_assert_num_queries
):
    api_client.force_authenticate(user=actor)
    category, kind = computing_category
    equipment_type = EquipmentType.objects.create(kind=kind, name="Query Budget Type")
    manufacturer = EquipmentManufacturer.objects.create(name="Query Budget Manufacturer")
    category.manufacturers.add(manufacturer)
    for index in range(3):
        EquipmentProductModel.objects.create(
            manufacturer=manufacturer,
            equipment_type=equipment_type,
            name=f"Query Budget Model {index}",
        )

    # Warm the per-user Labs role cache (one query on the first request) before measuring.
    api_client.get("/api/labs/equipment/computing/reference-data")
    with django_assert_num_queries(10):
        response = api_client.get("/api/labs/equipment/computing/reference-data")

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["data"]["product_models"]) == 3


@pytest.mark.django_db
def test_options_ordering_is_stable_by_name(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category

    eq_z = ComputingEquipment.objects.create(sku="EQ-Z", name="Zebra Machine", kind=kind)
    _set_status(eq_z, EquipmentStatus.AVAILABLE, actor)
    eq_a = ComputingEquipment.objects.create(sku="EQ-A", name="Apple Machine", kind=kind)
    _set_status(eq_a, EquipmentStatus.AVAILABLE, actor)
    eq_m = ComputingEquipment.objects.create(sku="EQ-M", name="Mango Machine", kind=kind)
    _set_status(eq_m, EquipmentStatus.AVAILABLE, actor)

    resp = api_client.get("/api/labs/equipment/options", {"q": "Machine"})
    assert resp.status_code == status.HTTP_200_OK
    names = [i["name"] for i in resp.data["data"]]
    assert names == sorted(names)


@pytest.mark.django_db
def test_options_status_and_assigned_filters(api_client, actor, computing_category, bench):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category

    eq1 = ComputingEquipment.objects.create(sku="EQ-F1", name="Eq Available", kind=kind)
    _set_status(eq1, EquipmentStatus.AVAILABLE, actor)

    eq2 = ComputingEquipment.objects.create(sku="EQ-F2", name="Eq In Use", kind=kind)
    _set_status(eq2, EquipmentStatus.IN_USE, actor)

    eq3 = ComputingEquipment.objects.create(sku="EQ-F3", name="Eq Assigned", kind=kind)
    _set_status(eq3, EquipmentStatus.AVAILABLE, actor)
    EquipmentAssignment.objects.create(
        equipment=eq3,
        bench=bench,
        assigned_at=timezone.now(),
        creator=actor,
        last_modified_by=actor,
    )

    # Filter by lifecycle_status
    resp = api_client.get("/api/labs/equipment/options", {"lifecycle_status": "available", "q": "Eq"})
    assert resp.status_code == status.HTTP_200_OK
    ids = [i["id"] for i in resp.data["data"]]
    assert eq1.pk in ids
    assert eq3.pk in ids
    assert eq2.pk not in ids

    # Filter by assigned=true
    resp_assigned = api_client.get("/api/labs/equipment/options", {"assigned": "true", "q": "Eq"})
    assert resp_assigned.status_code == status.HTTP_200_OK
    assigned_ids = [i["id"] for i in resp_assigned.data["data"]]
    assert eq3.pk in assigned_ids
    assert eq1.pk not in assigned_ids
    assert eq2.pk not in assigned_ids


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "equipment_model"),
    (
        ("/api/labs/equipment/options", ComputingEquipment),
        ("/api/labs/equipment/computing/options", ComputingEquipment),
    ),
)
def test_include_ids_include_nonmatching_active_but_exclude_soft_deleted(
    api_client, actor, computing_category, path, equipment_model
):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category
    active = equipment_model.objects.create(sku="EQ-INCLUDE", name="Included Active", kind=kind)
    deleted = equipment_model.objects.create(
        sku="EQ-DELETED-INCLUDE",
        name="Included Deleted",
        kind=kind,
        deleted_at=timezone.now(),
    )

    response = api_client.get(
        path,
        {"q": "no match", "include_ids": f"{active.pk},{deleted.pk}"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in response.data["data"]] == [active.pk]


@pytest.mark.django_db
def test_include_ids_count_toward_selector_result_cap(api_client, actor, computing_category, monkeypatch):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category
    included = ComputingEquipment.objects.create(sku="EQ-INCLUDE-CAP", name="Included by ID", kind=kind)
    ComputingEquipment.objects.create(sku="EQ-ORDINARY-CAP", name="Ordinary match", kind=kind)

    from core.labs.features.equipment.api.views import EquipmentOptionsAPIView

    monkeypatch.setattr(EquipmentOptionsAPIView, "max_results", 1)
    response = api_client.get(
        "/api/labs/equipment/options",
        {"q": "Ordinary", "include_ids": str(included.pk)},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "too_many_results"


@pytest.mark.django_db
def test_equipment_options_query_count_is_bounded_as_results_grow(
    api_client, actor, computing_category, django_assert_num_queries
):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category
    ComputingEquipment.objects.create(sku="EQ-QUERY-1", name="Query Item 1", kind=kind)
    # Warm the per-user Labs role cache (one query on the first request) before measuring.
    api_client.get("/api/labs/equipment/options", {"q": "Query Item"})

    with django_assert_num_queries(1):
        one_result = api_client.get("/api/labs/equipment/options", {"q": "Query Item"})
    assert one_result.status_code == status.HTTP_200_OK
    assert len(one_result.data["data"]) == 1

    for index in range(2, 101):
        ComputingEquipment.objects.create(
            sku=f"EQ-QUERY-{index}",
            name=f"Query Item {index}",
            kind=kind,
        )

    with django_assert_num_queries(1):
        many_results = api_client.get("/api/labs/equipment/options", {"q": "Query Item"})
    assert many_results.status_code == status.HTTP_200_OK
    assert len(many_results.data["data"]) == 100


@pytest.mark.django_db
def test_category_options_isolates_by_category(api_client, actor, computing_category, display_category):
    api_client.force_authenticate(user=actor)
    _, computing_kind = computing_category
    _, display_kind = display_category
    comp_eq = ComputingEquipment.objects.create(sku="OPT-COMPUTING", name="PC", kind=computing_kind)
    disp_eq = DisplayEquipment.objects.create(sku="OPT-DISPLAY", name="Monitor", kind=display_kind)
    _set_status(comp_eq, EquipmentStatus.AVAILABLE, actor)
    _set_status(disp_eq, EquipmentStatus.AVAILABLE, actor)

    # Category computing options?assignable=true
    comp_resp = api_client.get("/api/labs/equipment/computing/options", {"assignable": "true", "q": "PC"})
    assert comp_resp.status_code == status.HTTP_200_OK
    disp_resp = api_client.get("/api/labs/equipment/display/options", {"assignable": "true", "q": "Monitor"})
    assert disp_resp.status_code == status.HTTP_200_OK
    disp_ids = [item["id"] for item in disp_resp.data["data"]]
    assert disp_eq.pk in disp_ids
    assert comp_eq.pk not in disp_ids


@pytest.mark.django_db
def test_options_q_filter(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    _, kind = computing_category

    eq1 = ComputingEquipment.objects.create(sku="SRCH-ALPHA", name="Alpha Station", kind=kind)
    _set_status(eq1, EquipmentStatus.AVAILABLE, actor)

    eq2 = ComputingEquipment.objects.create(sku="SRCH-BETA", name="Beta Station", kind=kind)
    _set_status(eq2, EquipmentStatus.AVAILABLE, actor)

    resp = api_client.get("/api/labs/equipment/options", {"q": "Alpha", "assignable": "true"})
    assert resp.status_code == status.HTTP_200_OK
    ids = [item["id"] for item in resp.data["data"]]
    assert eq1.pk in ids
    assert eq2.pk not in ids


@pytest.mark.django_db
def test_new_equipment_selectors_and_catalogs(api_client, actor, computing_category):
    api_client.force_authenticate(user=actor)
    category, kind = computing_category

    etype = EquipmentType.objects.create(kind=kind, name="Laptop Type")
    mfr = EquipmentManufacturer.objects.create(name="Lenovo")
    mfr.categories.add(category)
    EquipmentProductModel.objects.create(manufacturer=mfr, equipment_type=etype, name="ThinkPad T14")
    dept = Department.objects.create(name="Engineering")
    ResourceGroup.objects.create(department=dept, name="Embedded Systems")

    # Categories
    resp_cats = api_client.get("/api/labs/equipment-categories/options")
    assert resp_cats.status_code == status.HTTP_200_OK
    assert any(c["name"] == "Computing" and c["sku"] == "computing" for c in resp_cats.data["data"])

    # Kinds
    resp_kinds = api_client.get(f"/api/labs/equipment-kinds/options?category_id={category.pk}")
    assert resp_kinds.status_code == status.HTTP_200_OK
    assert any(k["name"] == "Computer" for k in resp_kinds.data["data"])

    # Types
    resp_types = api_client.get(f"/api/labs/equipment-types/options?kind_id={kind.pk}")
    assert resp_types.status_code == status.HTTP_200_OK
    assert any(t["name"] == "Laptop Type" for t in resp_types.data["data"])

    # Manufacturers
    resp_mfrs = api_client.get(f"/api/labs/equipment-manufacturers/options?category_id={category.pk}")
    assert resp_mfrs.status_code == status.HTTP_200_OK
    assert any(m["name"] == "Lenovo" for m in resp_mfrs.data["data"])

    # Models
    resp_models = api_client.get(f"/api/labs/equipment-product-models/options?manufacturer_id={mfr.pk}")
    assert resp_models.status_code == status.HTTP_200_OK
    assert any(mod["name"] == "ThinkPad T14" for mod in resp_models.data["data"])

    # Departments
    resp_depts = api_client.get("/api/labs/departments/options")
    assert resp_depts.status_code == status.HTTP_200_OK
    assert any(d["name"] == "Engineering" for d in resp_depts.data["data"])

    # Resource Groups
    resp_rgs = api_client.get(f"/api/labs/resource-groups/options?department_id={dept.pk}")
    assert resp_rgs.status_code == status.HTTP_200_OK
    assert any(r["name"] == "Embedded Systems" for r in resp_rgs.data["data"])
