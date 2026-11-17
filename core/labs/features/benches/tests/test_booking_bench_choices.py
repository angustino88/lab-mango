"""GET /api/labs/benches/booking-choices: benches to book, each with the computers on it (name and hostname)."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import Bench, Equipment, EquipmentAssignment, EquipmentCategory, EquipmentKind
from tests.factories import UserFactory, create_computing_equipment, grant_labs_role

URL = "/api/labs/benches/booking-choices"
pytestmark = pytest.mark.django_db


@pytest.fixture()
def client():
    api_client = APIClient()
    user: Any = UserFactory()
    api_client.force_authenticate(user=grant_labs_role(user, "user"))
    return api_client


def _place(bench, unit, position=0):
    EquipmentAssignment.objects.create(
        bench=bench, equipment=unit, position=position, assigned_at=timezone.now() - timedelta(hours=1)
    )


@pytest.fixture()
def benches():
    computing = EquipmentKind.objects.create(
        category=EquipmentCategory.objects.create(name="Computing", definition="computers", monitored=True),
        name="Desktop",
    )
    display = EquipmentKind.objects.create(
        category=EquipmentCategory.objects.create(name="Display", definition="screens", monitored=False),
        name="Monitor",
    )
    radar = Bench.objects.create(sku="BK-B-1", name="Radar bench")
    video = Bench.objects.create(sku="BK-B-2", name="Video bench")
    retired = Bench.objects.create(sku="BK-B-3", name="Old bench", lifecycle_status="retired")
    _place(
        radar, create_computing_equipment(sku="PC-1", name="HCM-RADAR-PC01", kind=computing, hostname="hcm-radar-01")
    )
    _place(radar, create_computing_equipment(sku="PC-2", name="HCM-RADAR-PC02", kind=computing), position=1)
    _place(radar, Equipment.objects.create(sku="MON-1", name="Monitor 1", kind=display))
    return {"radar": radar, "video": video, "retired": retired}


def test_lists_in_service_benches_with_their_computers(client, benches):
    response = client.get(URL)

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert [bench["sku"] for bench in data] == ["BK-B-1", "BK-B-2"]  # ordered by name; retired left out
    assert data[0]["computers"] == [
        {"id": data[0]["computers"][0]["id"], "sku": "PC-1", "name": "HCM-RADAR-PC01", "hostname": "hcm-radar-01"},
        {"id": data[0]["computers"][1]["id"], "sku": "PC-2", "name": "HCM-RADAR-PC02", "hostname": ""},
    ]  # the monitor is not a computer
    assert data[1]["computers"] == []


@pytest.mark.parametrize("q", ["radar-pc02", "hcm-radar-01", "pc-1", "radar bench"])
def test_search_finds_a_bench_by_its_computer(client, benches, q):
    data = client.get(URL, {"q": q}).json()["data"]

    assert [bench["sku"] for bench in data] == ["BK-B-1"]


def test_include_ids_adds_the_bench_of_an_existing_booking(client, benches):
    data = client.get(URL, {"include_ids": str(benches["retired"].pk)}).json()["data"]

    assert "BK-B-3" in [bench["sku"] for bench in data]


def test_has_computing_keeps_only_benches_with_a_computer(client, benches):
    data = client.get(URL, {"has_computing": "true"}).json()["data"]

    assert [bench["sku"] for bench in data] == ["BK-B-1"]  # BK-B-2 has no computer


def test_has_computing_still_includes_the_bench_of_an_existing_booking(client, benches):
    params = {"has_computing": "true", "include_ids": str(benches["video"].pk)}
    data = client.get(URL, params).json()["data"]

    assert [bench["sku"] for bench in data] == ["BK-B-1", "BK-B-2"]


def test_unknown_parameter_is_400(client, benches):
    response = client.get(URL, {"status": "in_service"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


def test_two_queries_whatever_the_number_of_benches(client, benches, django_assert_max_num_queries):
    for index in range(15):
        bench = Bench.objects.create(sku=f"BK-X-{index:02}", name=f"Extra {index:02}")
        _place(
            bench,
            create_computing_equipment(
                sku=f"PC-X-{index:02}", kind=benches["radar"].equipment_assignments.first().equipment.kind
            ),
        )

    # Authentication and permission reads plus 2 (benches, computers).
    with django_assert_max_num_queries(9):
        assert client.get(URL).status_code == 200
