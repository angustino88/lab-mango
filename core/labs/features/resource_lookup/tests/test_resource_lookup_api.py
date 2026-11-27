"""GET /api/labs/resources/lookup: name, UID or SKU to typed resources, filtered by what the caller may read."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.labs.models import Bench, Room, Station
from core.users.tests.factories import UserFactory
from tests.factories import create_computing_equipment, grant_labs_role

URL = "/api/labs/resources/lookup"


def _client(username, role):
    client = APIClient()
    client.force_authenticate(user=grant_labs_role(UserFactory(username=username), role))
    return client


@pytest.fixture()
def member(db):
    return _client("lookup-member", "member")


@pytest.fixture()
def operator(db):
    return _client("lookup-operator", "coord")


@pytest.fixture()
def resources(db):
    room = Room.objects.create(sku="RM-301", name="Room 3.01")
    station = Station.objects.create(sku="ST-2", name="Station 2", room=room)
    bench = Bench.objects.create(sku="BN-A12", name="A-12", setup_location=station)
    retired = Bench.objects.create(sku="BN-A12-OLD", name="A-12 old", lifecycle_status="retired")
    equipment = create_computing_equipment(sku="SC-07", name="Scope SC-07")
    return {"room": room, "station": station, "bench": bench, "retired": retired, "equipment": equipment}


def _types(response):
    return [(item["type"]["value"], item["resource"]["name"]) for item in response.json()["data"]]


@pytest.mark.django_db
class TestLookup:
    def test_member_finds_only_bookable_benches(self, member, resources):
        response = member.get(URL, {"q": "A-12"})

        assert response.status_code == 200
        assert _types(response) == [("bench", "A-12")]
        item = response.json()["data"][0]
        assert item["match"] == {"value": "name_exact", "label": "Exact name"}
        assert item["context"] == "Station 2 · Room 3.01"

    def test_member_asking_for_equipment_gets_nothing(self, member, resources):
        response = member.get(URL, {"q": "SC-07", "types": "equipment"})

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_operator_finds_every_type(self, operator, resources):
        assert ("equipment", "Scope SC-07") in _types(operator.get(URL, {"q": "SC-07"}))
        assert ("room", "Room 3.01") in _types(operator.get(URL, {"q": "Room 3"}))
        assert ("station", "Station 2") in _types(operator.get(URL, {"q": "ST-2"}))
        assert {("bench", "A-12"), ("bench", "A-12 old")} <= set(_types(operator.get(URL, {"q": "A-12"})))

    def test_exact_uid_ranks_first(self, operator, resources):
        bench = resources["bench"]

        response = operator.get(URL, {"q": str(bench.uid), "types": "bench"})

        assert response.json()["data"][0]["resource"]["id"] == bench.pk
        assert response.json()["data"][0]["match"]["value"] == "uid_exact"

    def test_exact_sku_beats_prefix(self, operator, resources):
        data = operator.get(URL, {"q": "BN-A12", "types": "bench"}).json()["data"]

        assert [item["match"]["value"] for item in data] == ["sku_exact", "prefix"]

    def test_limit_per_type(self, operator, resources):
        data = operator.get(URL, {"q": "A-12", "types": "bench", "limit": 1}).json()["data"]

        assert len(data) == 1

    def test_one_query_per_type(self, operator, resources):
        operator.get(URL, {"q": "A", "types": "bench"})
        with CaptureQueriesContext(connection) as one:
            operator.get(URL, {"q": "A", "types": "bench"})
        with CaptureQueriesContext(connection) as all_types:
            operator.get(URL, {"q": "A"})

        assert len(all_types) - len(one) == 4

    @pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "A", "types": "desk"}, {"q": "A", "limit": "11"}])
    def test_bad_query_is_400(self, operator, params):
        assert operator.get(URL, params).status_code == 400

    def test_anonymous_is_refused(self):
        assert APIClient().get(URL, {"q": "A"}).status_code in (401, 403)
