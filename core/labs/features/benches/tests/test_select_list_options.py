"""OPT behavior for GET /api/labs/benches/options (ADR 002)."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.features.benches.api import views
from core.labs.models import Bench, BenchFavorite, BenchGroup, BenchType
from tests.factories import grant_labs_role

URL = "/api/labs/benches/options"
GROUPS_URL = "/api/labs/bench-groups/options"
TYPES_URL = "/api/labs/bench-types/options"


@pytest.fixture()
def actor(db):
    return get_user_model().objects.create_user(username="select_actor", email="select@example.com")


@pytest.fixture()
def client(actor):
    api_client = APIClient()
    grant_labs_role(actor, "coord")
    api_client.force_authenticate(user=actor)
    return api_client


@pytest.mark.django_db
def test_unauthenticated_select_list_rejected():
    assert APIClient().get(URL, {"q": "Bench"}).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_options_without_filter_returns_all_benches(client):
    Bench.objects.create(name="Bench 1", sku="B-1")
    response = client.get(URL)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["data"]) >= 1


@pytest.mark.django_db
def test_items_have_exactly_id_sku_name_and_no_pagination(client):
    bench = Bench.objects.create(name="Bench A", sku="BENCH-SEL-01")

    response = client.get(URL, {"q": "Bench"})

    assert response.status_code == status.HTTP_200_OK
    assert "meta" not in response.data or "pagination" not in response.data.get("meta", {})
    assert response.data["data"] == [{"id": bench.pk, "sku": "BENCH-SEL-01", "name": "Bench A"}]


@pytest.mark.django_db
def test_ordering_is_fixed_by_name_then_id(client):
    Bench.objects.create(name="Zulu", sku="B-1")
    first = Bench.objects.create(name="Alpha", sku="B-2")
    second = Bench.objects.create(name="Alpha", sku="B-0")

    response = client.get(URL, {"ordering": "-name"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    response = client.get(URL, {"q": "B"})
    names = [(item["name"], item["id"]) for item in response.data["data"]]
    assert names == sorted(names)
    assert [item["id"] for item in response.data["data"][:2]] == sorted([first.pk, second.pk])


@pytest.mark.django_db
def test_soft_deleted_benches_are_excluded(client):
    live = Bench.objects.create(name="Live", sku="B-LIVE")
    Bench.objects.create(name="Gone", sku="B-GONE", deleted_at=timezone.now())

    response = client.get(URL, {"q": "B"})

    assert [item["id"] for item in response.data["data"]] == [live.pk]


@pytest.mark.django_db
def test_unknown_query_parameter_returns_400(client):
    response = client.get(URL, {"unknown_filter": "x"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "invalid_query"


@pytest.mark.django_db
def test_favorite_filter_uses_callers_bookmarks(client, actor):
    mine = Bench.objects.create(name="Mine", sku="B-MINE")
    Bench.objects.create(name="Other", sku="B-OTHER")
    BenchFavorite.objects.create(user=actor, bench=mine)

    response = client.get(URL, {"favorite": "true"})

    assert [item["id"] for item in response.data["data"]] == [mine.pk]


@pytest.mark.django_db
def test_result_over_cap_returns_too_many_results(client, monkeypatch):
    monkeypatch.setattr(views, "BENCH_OPTIONS_MAX_RESULTS", 2)
    for index in range(3):
        Bench.objects.create(name=f"Bench {index}", sku=f"B-CAP-{index}")

    response = client.get(URL, {"q": "Bench"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "too_many_results"
    assert "data" not in response.data


@pytest.mark.django_db
def test_etag_matches_returns_304(client):
    Bench.objects.create(name="Bench A", sku="B-A")
    response1 = client.get(URL, {"q": "Bench"})
    assert response1.status_code == status.HTTP_200_OK
    etag = response1.headers["ETag"]

    response2 = client.get(URL, {"q": "Bench"}, HTTP_IF_NONE_MATCH=etag)
    assert response2.status_code == status.HTTP_304_NOT_MODIFIED


@pytest.mark.django_db
def test_bench_group_and_type_options(client):
    group = BenchGroup.objects.create(name="Group 1", active=True)
    BenchGroup.objects.create(name="Inactive Group", active=False)
    btype = BenchType.objects.create(name="Type 1", active=True)
    BenchType.objects.create(name="Inactive Type", active=False)

    resp_groups = client.get(GROUPS_URL)
    assert resp_groups.status_code == status.HTTP_200_OK
    assert resp_groups.data["data"] == [{"id": group.pk, "sku": None, "name": "Group 1"}]

    resp_types = client.get(TYPES_URL)
    assert resp_types.status_code == status.HTTP_200_OK
    assert resp_types.data["data"] == [{"id": btype.pk, "sku": None, "name": "Type 1"}]
