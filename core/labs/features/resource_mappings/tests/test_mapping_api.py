"""API contract tests for flat resource placement mappings."""

from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import (
    Bench,
    ComputingActivity,
    Equipment,
    EquipmentAssignment,
    EquipmentCategory,
    EquipmentKind,
    License,
    LicenseAssignment,
    Room,
    RoomSlot,
    Station,
    StationSlot,
)
from core.labs.models.resource.license.license import (
    LicenseCategory,
    LicenseProduct,
    LicenseType,
    LicenseVendor,
)
from tests.factories import UserFactory, create_computing_equipment, grant_labs_role


@pytest.fixture()
def client(db):
    api_client = APIClient()
    api_client.force_authenticate(user=grant_labs_role(UserFactory(), "coord"))
    return api_client


@pytest.fixture()
def placement():
    room = Room.objects.create(sku="MAP-R-1", name="Mapping room", layout_rows=2, layout_columns=3)
    room_slot = RoomSlot.objects.create(room=room, row_index=1, col_index=2, slot_code="R1C2")
    station = Station.objects.create(sku="MAP-S-1", name="Mapping station", room=room, slot=room_slot)
    station_slot = StationSlot.objects.create(
        station=station,
        position_index=2,
        slot_code="BENCH-2",
        label="Bench position two",
    )
    bench = Bench.objects.create(
        sku="MAP-B-1",
        name="Mapping bench",
        setup_location=station,
        station_slot=station_slot,
    )
    category = EquipmentCategory.objects.create(name="Mapping category", definition="Synthetic mapping fixture")
    kind = EquipmentKind.objects.create(category=category, name="Mapping equipment")
    equipment = Equipment.objects.create(sku="MAP-E-1", name="Mapping equipment one", kind=kind)
    assignment = EquipmentAssignment.objects.create(
        bench=bench,
        equipment=equipment,
        role="host",
        position=4,
        monitor=True,
        assigned_at=timezone.now() - timedelta(days=1),
    )
    license_category = LicenseCategory.objects.create(name="Mapping license category")
    license_item = License.objects.create(
        sku="MAP-L-1",
        name="Mapping license",
        product=LicenseProduct.objects.create(name="Mapping product"),
        vendor=LicenseVendor.objects.create(name="Mapping vendor"),
        type=LicenseType.objects.create(name="Mapping type"),
        category=license_category,
        identifier="must-not-be-returned",
    )
    license_assignment = LicenseAssignment.objects.create(
        equipment=equipment,
        license=license_item,
        assigned_at=timezone.now() - timedelta(hours=2),
    )
    return {
        "room": room,
        "room_slot": room_slot,
        "station": station,
        "station_slot": station_slot,
        "bench": bench,
        "equipment": equipment,
        "equipment_assignment": assignment,
        "license": license_item,
        "license_assignment": license_assignment,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("resource", "root_collection"),
    [("rooms", "rooms"), ("stations", "stations"), ("benches", "benches"), ("equipment", "equipment")],
)
def test_mapping_endpoints_return_flat_placement_closure(client, placement, resource, root_collection):
    resource_key = {"rooms": "room", "stations": "station", "benches": "bench", "equipment": "equipment"}[resource]
    item = placement[resource_key]
    response = client.get(f"/api/labs/{resource}/{item.pk}/mapping")

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {
        "rooms",
        "room_slots",
        "stations",
        "station_slots",
        "benches",
        "equipment",
        "licenses",
        "license_assignments",
    }
    assert item.pk in {row["id"] for row in data[root_collection]}
    assert data["rooms"][0]["id"] == placement["room"].pk
    assert data["room_slots"][0]["id"] == placement["room_slot"].pk
    assert data["stations"][0]["id"] == placement["station"].pk
    assert data["station_slots"][0]["id"] == placement["station_slot"].pk
    assert data["benches"][0]["id"] == placement["bench"].pk
    equipment_row = data["equipment"][0]
    assert equipment_row["id"] == placement["equipment"].pk
    assert equipment_row["bench_id"] == placement["bench"].pk
    assert equipment_row["bench_assignment"] == {
        "id": placement["equipment_assignment"].pk,
        "role": "host",
        "position": 4,
        "is_monitored": True,
        "assigned_at": equipment_row["bench_assignment"]["assigned_at"],
    }
    assert data["licenses"] == [
        {
            "id": placement["license"].pk,
            "uid": str(placement["license"].uid),
            "sku": "MAP-L-1",
            "name": "Mapping license",
            "category": {"id": placement["license"].category_id, "name": "Mapping license category"},
        }
    ]
    assert data["license_assignments"] == [
        {
            "id": placement["license_assignment"].pk,
            "equipment_id": placement["equipment"].pk,
            "license_id": placement["license"].pk,
            "assigned_at": data["license_assignments"][0]["assigned_at"],
        }
    ]
    assert "must-not-be-returned" not in response.content.decode()
    assert all("identifier" not in row and "owner" not in row and "price" not in row for row in data["licenses"])
    assert "status" not in equipment_row
    assert "bookings" not in equipment_row
    assert "activity" not in equipment_row
    assert "nodes" not in data and "edges" not in data
    assert set(response.json()["meta"]["pagination"]) == set(data)


@pytest.mark.django_db
def test_room_and_station_mapping_include_all_configured_descendants(client, placement):
    second_slot = StationSlot.objects.create(
        station=placement["station"],
        position_index=3,
        slot_code="BENCH-3",
        label="Bench position three",
    )
    second_bench = Bench.objects.create(
        sku="MAP-B-2",
        name="Second mapping bench",
        setup_location=placement["station"],
        station_slot=second_slot,
    )
    second_equipment = Equipment.objects.create(
        sku="MAP-E-2",
        name="Second mapping equipment",
        kind=placement["equipment"].kind,
    )
    EquipmentAssignment.objects.create(bench=second_bench, equipment=second_equipment, assigned_at=timezone.now())

    for resource, key in (("rooms", "room"), ("stations", "station")):
        root = placement[key]
        data = client.get(f"/api/labs/{resource}/{root.pk}/mapping").json()["data"]
        assert {row["id"] for row in data["benches"]} == {placement["bench"].pk, second_bench.pk}
        assert {row["id"] for row in data["equipment"]} == {placement["equipment"].pk, second_equipment.pk}


@pytest.mark.django_db
def test_unplaced_equipment_and_soft_deleted_descendants_are_excluded(client, placement):
    category = EquipmentCategory.objects.create(name="Computing", definition="Synthetic computing fixture")
    kind = EquipmentKind.objects.create(category=category, name="Mapping computer")
    equipment = create_computing_equipment(
        sku="MAP-E-UNPLACED",
        name="Unplaced equipment",
        kind=kind,
    )
    ComputingActivity.objects.create(
        computing=equipment,
        status="offline",
        offline_at=timezone.now(),
        last_agent_report_at=timezone.now(),
    )
    response = client.get(f"/api/labs/equipment/{equipment.pk}/mapping")
    assert response.status_code == 200
    data = response.json()["data"]
    assert [row["id"] for row in data["equipment"]] == [equipment.pk]
    assert data["equipment"][0]["bench_id"] is None
    assert data["equipment"][0]["bench_assignment"] is None
    assert all(not rows for name, rows in data.items() if name != "equipment")

    Equipment.objects.filter(pk=placement["equipment"].pk).update(deleted_at=timezone.now())
    response = client.get(f"/api/labs/benches/{placement['bench'].pk}/mapping")
    assert response.status_code == 200
    assert response.json()["data"]["equipment"] == []
    assert response.json()["data"]["licenses"] == []
    assert response.json()["data"]["license_assignments"] == []


@pytest.mark.django_db
def test_mapping_filters_inactive_bench_and_license_assignments(client, placement):
    assigned = Equipment.objects.create(
        sku="MAP-E-OLD",
        name="Previously assigned equipment",
        kind=placement["equipment"].kind,
    )
    old_assignment = EquipmentAssignment.objects.create(
        bench=placement["bench"],
        equipment=assigned,
        assigned_at=timezone.now() - timedelta(days=2),
        unassigned_at=timezone.now() - timedelta(days=1),
    )
    old_license = License.objects.create(
        sku="MAP-L-OLD",
        name="Previously assigned license",
        product=LicenseProduct.objects.create(name="Old product"),
        vendor=LicenseVendor.objects.create(name="Old vendor"),
        type=LicenseType.objects.create(name="Old type"),
        category=LicenseCategory.objects.create(name="Old category"),
    )
    LicenseAssignment.objects.create(
        equipment=placement["equipment"],
        license=old_license,
        assigned_at=timezone.now() - timedelta(days=2),
        unassigned_at=timezone.now() - timedelta(days=1),
    )

    data = client.get(f"/api/labs/benches/{placement['bench'].pk}/mapping").json()["data"]
    assert assigned.pk not in {row["id"] for row in data["equipment"]}
    assert old_license.pk not in {row["id"] for row in data["licenses"]}
    assert old_assignment.pk not in {
        row["bench_assignment"]["id"]
        for row in data["equipment"]
        if row["bench_assignment"] is not None
    }


@pytest.mark.django_db
def test_cursor_pagination_is_per_collection_and_completes(client, placement):
    kind = placement["equipment"].kind
    for index in range(2):
        equipment = Equipment.objects.create(
            sku=f"MAP-E-{index + 2}",
            name=f"Mapping equipment {index + 2}",
            kind=kind,
        )
        EquipmentAssignment.objects.create(
            bench=placement["bench"],
            equipment=equipment,
            position=index + 5,
            assigned_at=timezone.now(),
        )

    response = client.get(f"/api/labs/benches/{placement['bench'].pk}/mapping?page_size=1")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["equipment"]) == 1
    pagination = response.json()["meta"]["pagination"]["equipment"]
    assert pagination["count"] == 3
    assert pagination["next_cursor"]
    assert pagination["previous_cursor"] is None

    seen = {data["equipment"][0]["id"]}
    cursor = pagination["next_cursor"]
    while cursor:
        page = client.get(
            f"/api/labs/benches/{placement['bench'].pk}/mapping?"
            f"{urlencode({'page_size': 1, 'equipment_cursor': cursor})}"
        )
        assert page.status_code == 200
        page_data = page.json()["data"]
        assert len(page_data["equipment"]) == 1
        seen.add(page_data["equipment"][0]["id"])
        cursor = page.json()["meta"]["pagination"]["equipment"]["next_cursor"]
    assert len(seen) == 3


@pytest.mark.django_db
def test_cursor_is_bound_to_root_collection_and_page_size(client, placement):
    for index in range(2):
        extra_equipment = Equipment.objects.create(
            sku=f"MAP-E-CURSOR-{index}",
            name=f"Cursor equipment {index}",
            kind=placement["equipment"].kind,
        )
        EquipmentAssignment.objects.create(
            bench=placement["bench"],
            equipment=extra_equipment,
            assigned_at=timezone.now(),
        )
    first = client.get(f"/api/labs/benches/{placement['bench'].pk}/mapping?page_size=1").json()
    cursor = first["meta"]["pagination"]["equipment"]["next_cursor"]
    assert cursor
    wrong_size = client.get(
        f"/api/labs/benches/{placement['bench'].pk}/mapping?"
        f"{urlencode({'page_size': 2, 'equipment_cursor': cursor})}"
    )
    wrong_collection = client.get(
        f"/api/labs/benches/{placement['bench'].pk}/mapping?"
        f"{urlencode({'page_size': 1, 'rooms_cursor': cursor})}"
    )
    wrong_root = client.get(
        f"/api/labs/rooms/{placement['room'].pk}/mapping?"
        f"{urlencode({'page_size': 1, 'equipment_cursor': cursor})}"
    )
    assert [wrong_size.status_code, wrong_collection.status_code, wrong_root.status_code] == [400, 400, 400]


@pytest.mark.django_db
def test_equipment_mapping_root_is_first_and_cursor_pages_siblings(client, placement):
    siblings = []
    for index in range(3):
        equipment = Equipment.objects.create(
            sku=f"MAP-E-SIBLING-{index}",
            name=f"Sibling equipment {index}",
            kind=placement["equipment"].kind,
        )
        EquipmentAssignment.objects.create(
            bench=placement["bench"],
            equipment=equipment,
            assigned_at=timezone.now(),
        )
        siblings.append(equipment)

    selected = siblings[-1]
    first = client.get(f"/api/labs/equipment/{selected.pk}/mapping?page_size=1").json()
    assert first["data"]["equipment"][0]["id"] == selected.pk
    cursor = first["meta"]["pagination"]["equipment"]["next_cursor"]
    seen = {selected.pk}
    while cursor:
        page = client.get(
            f"/api/labs/equipment/{selected.pk}/mapping?"
            f"{urlencode({'page_size': 1, 'equipment_cursor': cursor})}"
        ).json()
        seen.update(row["id"] for row in page["data"]["equipment"])
        cursor = page["meta"]["pagination"]["equipment"]["next_cursor"]
    assert seen == {item.pk for item in siblings} | {placement["equipment"].pk}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "page_size=101",
        "page_size=1&page_size=2",
        "bad_cursor=token",
        "equipment_cursor=invalid",
        "room_slots_cursor=not-signed",
    ],
)
def test_mapping_rejects_unknown_repeated_and_invalid_cursor_parameters(client, placement, query):
    response = client.get(f"/api/labs/benches/{placement['bench'].pk}/mapping?{query}")
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.django_db
def test_mapping_requires_authentication_and_hides_missing_resources(placement):
    client = APIClient()
    assert client.get(f"/api/labs/rooms/{placement['room'].pk}/mapping").status_code == 401
    client.force_authenticate(user=grant_labs_role(UserFactory(), "coord"))
    assert client.get("/api/labs/equipment/999999/mapping").status_code == 404


@pytest.mark.django_db
def test_mapping_query_count_is_bounded_for_multi_resource_closure(client, placement, django_assert_max_num_queries):
    for index in range(8):
        bench = Bench.objects.create(sku=f"MAP-B-BUDGET-{index}", name=f"Budget bench {index}",
                                     setup_location=placement["station"])
        equipment = Equipment.objects.create(
            sku=f"MAP-E-BUDGET-{index}", name=f"Budget equipment {index}", kind=placement["equipment"].kind
        )
        EquipmentAssignment.objects.create(bench=bench, equipment=equipment, assigned_at=timezone.now())
    with django_assert_max_num_queries(25):
        response = client.get(f"/api/labs/rooms/{placement['room'].pk}/mapping")
    assert response.status_code == 200
    assert len(response.json()["data"]["equipment"]) == 9
