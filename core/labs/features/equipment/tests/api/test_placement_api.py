"""HTTP contract of /api/labs/equipment/{id}/placement (redesign step 1)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import Bench, EquipmentCategory, EquipmentKind, Room
from tests.factories import create_computing_equipment

ROOT = "/api/labs/equipment/"
User = get_user_model()


@pytest.fixture
def unit(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name="API PC")
    return create_computing_equipment(sku="PL-API-1", name="API unit", kind=kind)


@pytest.fixture
def coordinator_client(db):
    client = APIClient()
    client.force_authenticate(grant_labs_role(User.objects.create_user(username="pl-coord"), "coord"))
    return client


@pytest.mark.django_db
def test_put_get_delete_room_placement(coordinator_client, unit):
    room = Room.objects.create(sku="PL-API-R", name="Store")
    url = f"{ROOT}{unit.pk}/placement"
    assert coordinator_client.get(url).status_code == 404

    put = coordinator_client.put(url, {"room_id": room.pk, "location_note": "  Shelf B "}, format="json")
    assert put.status_code == 200, put.data
    body = put.data["data"]
    assert body["target_type"]["value"] == "room"
    assert body["room"]["id"] == room.pk and body["bench"] is None and body["station"] is None
    assert body["location_note"] == "Shelf B"

    got = coordinator_client.get(url)
    assert got.status_code == 200 and got.data["data"]["id"] == body["id"]
    # The bench-only assignment route does not report a room placement.
    assert coordinator_client.get(f"{ROOT}{unit.pk}/assignment").status_code == 404

    assert coordinator_client.delete(url).status_code == 204
    assert coordinator_client.delete(url).status_code == 204
    assert coordinator_client.get(url).status_code == 404


@pytest.mark.django_db
def test_put_moves_off_a_bench_in_one_call(coordinator_client, unit):
    bench = Bench.objects.create(sku="PL-API-B", name="Bench")
    room = Room.objects.create(sku="PL-API-R2", name="Store 2")
    url = f"{ROOT}{unit.pk}/placement"
    on_bench = coordinator_client.put(url, {"bench_id": bench.pk, "role": "primary"}, format="json")
    assert on_bench.status_code == 200, on_bench.data
    assert on_bench.data["data"]["target_type"]["value"] == "bench"
    assert coordinator_client.get(f"{ROOT}{unit.pk}/assignment").status_code == 200
    moved = coordinator_client.put(url, {"room_id": room.pk}, format="json")
    assert moved.status_code == 200, moved.data
    assert moved.data["data"]["target_type"]["value"] == "room"
    assert coordinator_client.get(f"{ROOT}{unit.pk}/assignment").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"location_note": "   "}, {"room_id": 1, "station_id": 1}])
def test_put_rejects_invalid_targets(coordinator_client, unit, body):
    response = coordinator_client.put(f"{ROOT}{unit.pk}/placement", body, format="json")
    assert response.status_code == 422, response.data


@pytest.mark.django_db
def test_put_unknown_room_is_422(coordinator_client, unit):
    response = coordinator_client.put(f"{ROOT}{unit.pk}/placement", {"room_id": 999999}, format="json")
    assert response.status_code == 422


@pytest.mark.django_db
def test_plain_user_can_neither_read_nor_write_placement(unit):
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="pl-plain"))
    url = f"{ROOT}{unit.pk}/placement"
    assert client.put(url, {"location_note": "Desk"}, format="json").status_code == 403
    assert client.delete(url).status_code == 403
    assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_equipment_responses_include_placement(coordinator_client, unit):
    room = Room.objects.create(sku="PL-API-R3", name="Store 3")
    coordinator_client.put(f"{ROOT}{unit.pk}/placement", {"room_id": room.pk}, format="json")

    detail = coordinator_client.get(f"{ROOT}{unit.pk}").data["data"]
    assert detail["placement"]["target_type"]["value"] == "room"
    assert detail["placement"]["room"]["id"] == room.pk
    assert "storage_room" not in detail

    rows = coordinator_client.get(ROOT.rstrip("/"), {"search": unit.sku}).data["data"]
    assert [row["placement"]["room"]["id"] for row in rows] == [room.pk]

    coordinator_client.delete(f"{ROOT}{unit.pk}/placement")
    assert coordinator_client.get(f"{ROOT}{unit.pk}").data["data"]["placement"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("path", [""])
def test_list_placement_query_count_does_not_grow_with_rows(coordinator_client, unit, path):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    room = Room.objects.create(sku="PL-API-QR", name="Store Q")

    def seed(index):
        extra = create_computing_equipment(sku=f"PL-API-Q{path}{index}", name="Q", kind=unit.kind)
        coordinator_client.put(f"{ROOT}{extra.pk}/placement", {"room_id": room.pk}, format="json")

    def count():
        with CaptureQueriesContext(connection) as context:
            response = coordinator_client.get(f"{ROOT}{path}".rstrip("/"), {"page_size": 50})
        assert response.status_code == 200
        assert all(row["placement"] is not None for row in response.data["data"] if row["sku"].startswith("PL-API-Q"))
        return len(context.captured_queries)

    for index in range(2):
        seed(index)
    count()  # warm per-process caches
    small = count()
    for index in range(2, 8):
        seed(index)
    assert count() == small
