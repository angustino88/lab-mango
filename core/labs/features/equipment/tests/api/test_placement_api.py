"""HTTP contract of /api/labs/equipment/{id}/placement (redesign step 1)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import Bench, ComputingEquipment, EquipmentCategory, EquipmentKind, Room

ROOT = "/api/labs/equipment/"
User = get_user_model()


@pytest.fixture
def unit(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name="API PC")
    return ComputingEquipment.objects.create(sku="PL-API-1", name="API unit", kind=kind)


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
    assert body["target_type"] == "room"
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
def test_put_bench_then_room_conflicts(coordinator_client, unit):
    bench = Bench.objects.create(sku="PL-API-B", name="Bench")
    room = Room.objects.create(sku="PL-API-R2", name="Store 2")
    url = f"{ROOT}{unit.pk}/placement"
    on_bench = coordinator_client.put(url, {"bench_id": bench.pk, "role": "primary"}, format="json")
    assert on_bench.status_code == 200, on_bench.data
    assert on_bench.data["data"]["target_type"] == "bench"
    assert coordinator_client.get(f"{ROOT}{unit.pk}/assignment").status_code == 200
    conflict = coordinator_client.put(url, {"room_id": room.pk}, format="json")
    assert conflict.status_code == 409
    assert conflict.data["error"]["code"] == "equipment_already_placed"


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
def test_plain_user_can_read_but_not_write_placement(unit):
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="pl-plain"))
    url = f"{ROOT}{unit.pk}/placement"
    assert client.put(url, {"location_note": "Desk"}, format="json").status_code == 403
    assert client.delete(url).status_code == 403
    assert client.get(url).status_code == 404
