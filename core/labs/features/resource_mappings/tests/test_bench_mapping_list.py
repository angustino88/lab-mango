"""GET /api/labs/resource-mappings: one page of benches with what they are mapped to, filtered on the server."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import Bench, Equipment, EquipmentAssignment, EquipmentCategory, EquipmentKind, Room, Station
from tests.factories import UserFactory, grant_labs_role

from .test_mapping_api import placement  # noqa: F401 - fixture: a bench fully mapped (room, station, unit, license)

URL = "/api/labs/resource-mappings"
pytestmark = pytest.mark.django_db


@pytest.fixture()
def client(db):
    api_client = APIClient()
    user: Any = UserFactory()
    api_client.force_authenticate(user=grant_labs_role(user, "coord"))
    return api_client


@pytest.fixture()
def benches(placement):  # noqa: F811
    """MAP-B-1 fully mapped (placement fixture), MAP-B-2 placed but empty, MAP-B-3 not placed."""
    Bench.objects.create(sku="MAP-B-2", name="Empty bench", setup_location=placement["station"])
    Bench.objects.create(sku="MAP-B-3", name="Loose bench")
    return placement


def _data(response):
    assert response.status_code == 200, response.json()
    return response.json()


def test_lists_a_page_of_benches_with_only_the_rows_they_reference(client, benches):
    body = _data(client.get(URL))

    assert [bench["sku"] for bench in body["data"]["benches"]] == ["MAP-B-1", "MAP-B-2", "MAP-B-3"]
    assert [room["sku"] for room in body["data"]["rooms"]] == ["MAP-R-1"]
    assert [slot["slot_code"] for slot in body["data"]["room_slots"]] == ["R1C2"]
    assert [station["sku"] for station in body["data"]["stations"]] == ["MAP-S-1"]
    assert [slot["slot_code"] for slot in body["data"]["station_slots"]] == ["BENCH-2"]
    assert [unit["sku"] for unit in body["data"]["equipment"]] == ["MAP-E-1"]
    assert [item["sku"] for item in body["data"]["licenses"]] == ["MAP-L-1"]
    assert body["meta"]["summary"] == {
        "benches": 3,
        "fully_mapped": 1,
        "needs_equipment": 1,
        "needs_placement": 1,
        "equipment": 1,
    }
    assert body["meta"]["pagination"] == {"count": 3, "page": 1, "page_size": 25, "next": None, "previous": None}


@pytest.mark.parametrize(
    ("state", "skus"),
    [("fully_mapped", ["MAP-B-1"]), ("needs_equipment", ["MAP-B-2"]), ("needs_placement", ["MAP-B-3"])],
)
def test_state_filters_the_page_but_not_the_summary(client, benches, state, skus):
    body = _data(client.get(URL, {"state": state}))

    assert [bench["sku"] for bench in body["data"]["benches"]] == skus
    assert body["meta"]["pagination"]["count"] == 1
    assert body["meta"]["summary"]["benches"] == 3


def test_search_matches_bench_station_room_and_placed_units(client, benches):
    by_unit = _data(client.get(URL, {"q": "map-e-1"}))
    by_room = _data(client.get(URL, {"q": "Mapping room"}))

    assert [bench["sku"] for bench in by_unit["data"]["benches"]] == ["MAP-B-1"]
    assert [bench["sku"] for bench in by_room["data"]["benches"]] == ["MAP-B-1", "MAP-B-2"]


def test_room_station_and_category_filters(client, benches):
    room = benches["room"]
    category = benches["equipment"].kind.category

    assert len(_data(client.get(URL, {"room_id": room.pk}))["data"]["benches"]) == 2
    assert len(_data(client.get(URL, {"station_id": benches["station"].pk}))["data"]["benches"]) == 2
    only = _data(client.get(URL, {"equipment_category_id": category.pk}))
    assert [bench["sku"] for bench in only["data"]["benches"]] == ["MAP-B-1"]


def test_pages_carry_ready_to_call_links(client, benches):
    first = _data(client.get(URL, {"page_size": 2}))
    second = _data(client.get(URL, {"page_size": 2, "page": 2}))

    assert len(first["data"]["benches"]) == 2
    assert "page=2" in first["meta"]["pagination"]["next"] and "page_size=2" in first["meta"]["pagination"]["next"]
    assert [bench["sku"] for bench in second["data"]["benches"]] == ["MAP-B-3"]
    assert second["meta"]["pagination"]["next"] is None
    assert "page=" not in second["meta"]["pagination"]["previous"]


@pytest.mark.parametrize(
    "query",
    [{"page_size": 101}, {"state": "unknown"}, {"room": 1}, {"page": 0}],
)
def test_invalid_queries_are_400(client, benches, query):
    response = client.get(URL, query)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


def test_query_count_does_not_grow_with_the_page(client, benches, django_assert_max_num_queries):
    category = EquipmentCategory.objects.create(name="Budget category", definition="query budget")
    kind = EquipmentKind.objects.create(category=category, name="Budget kind")
    room = Room.objects.create(sku="MAP-R-9", name="Budget room")
    for index in range(20):
        station = Station.objects.create(sku=f"MAP-S-9{index:02}", name="Budget station", room=room)
        bench = Bench.objects.create(sku=f"MAP-B-9{index:02}", name="Budget bench", setup_location=station)
        unit = Equipment.objects.create(sku=f"MAP-E-9{index:02}", name="Budget unit", kind=kind)
        EquipmentAssignment.objects.create(
            bench=bench, equipment=unit, assigned_at=timezone.now() - timedelta(hours=1)
        )

    # Authentication and permission reads, 9 mapping queries, 3 visual-model lookups and 4 DCIM reads
    # (conditions, installed totals x2, rack contents); fixed whatever the page size.
    with django_assert_max_num_queries(20):
        body = _data(client.get(URL, {"page_size": 25}))

    assert len(body["data"]["benches"]) == 23


def test_a_page_beyond_the_last_is_404(client, benches):
    response = client.get(URL, {"page": 2})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_needs_staff_access(benches):
    member = APIClient()
    user: Any = UserFactory()
    member.force_authenticate(user=grant_labs_role(user, "member"))

    assert member.get(URL).status_code == 403
