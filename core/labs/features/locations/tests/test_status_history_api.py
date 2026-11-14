"""Room and station status history: rows name who recorded each status."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.labs.models import Room, Station, StationType
from core.users.models import User
from tests.factories import grant_labs_role


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="loc-hist-coord", display_name="Coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


@pytest.fixture
def room(db):
    return Room.objects.create(name="History room", sku="ROOM-HIST")


@pytest.fixture
def station(db):
    return Station.objects.create(name="History station", sku="ST-HIST", type=StationType.objects.create(name="Hist"))


def _resource(kind, room, station):
    return ("rooms", room) if kind == "room" else ("stations", station)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["room", "station"])
def test_history_rows_name_the_actor(client, coordinator, room, station, kind):
    path, resource = _resource(kind, room, station)
    for value in ("maintenance", "available"):
        changed = client.post(
            f"/api/labs/{path}/{resource.pk}/actions/change-status", {"status": value}, format="json"
        )
        assert changed.status_code == 200, changed.data

    response = client.get(f"/api/labs/{path}/{resource.pk}/history")

    assert response.status_code == 200, response.data
    rows = response.data["data"]
    # Records hold the lifecycle; the deprecated value written is kept in metadata.
    assert [row["status"]["value"] for row in rows] == ["in_service", "in_service"]
    assert [row["metadata"]["legacy_status"] for row in rows] == ["available", "maintenance"]
    assert rows[0]["actor"] == {"id": coordinator.pk, "name": "Coord"}
    assert set(rows[0]) == {"id", kind, "status", "metadata", "actor", "created_at"}


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["room", "station"])
def test_history_actor_is_null_when_unknown(client, room, station, kind):
    path, resource = _resource(kind, room, station)
    resource.status_records.create(status="available")

    rows = client.get(f"/api/labs/{path}/{resource.pk}/history").data["data"]

    assert rows[0]["actor"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["room", "station"])
def test_history_query_count_does_not_grow_with_rows(client, room, station, kind):
    path, resource = _resource(kind, room, station)
    url = f"/api/labs/{path}/{resource.pk}/history"

    def seed(count):
        for index in range(count):
            user = User.objects.create_user(username=f"loc-hist-{kind}-{resource.status_records.count()}-{index}")
            record = resource.status_records.model(**{kind: resource, "status": "available"})
            record.save(actor=user)

    def queries():
        with CaptureQueriesContext(connection) as captured:
            assert client.get(url).status_code == 200
        return len(captured)

    seed(1)
    client.get(url)  # warm the per-user Labs role cache
    one = queries()
    seed(5)
    assert queries() == one
