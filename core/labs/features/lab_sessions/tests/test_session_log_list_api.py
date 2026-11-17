"""A6 (flat view): GET /api/labs/lab-sessions."""

from datetime import date, datetime, time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import SessionAccessType
from tests.factories import BenchFactory, LabSessionLogFactory, UserFactory, grant_labs_role

URL = "/api/labs/lab-sessions"
DAY = date(2026, 11, 10)


def at(day: date, hour: int) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour)))


def session(day: date = DAY, hour: int = 9, minutes: int = 60, **values):
    login = at(day, hour)
    return LabSessionLogFactory(login_time=login, logout_time=login + timedelta(minutes=minutes), **values)


@pytest.fixture()
def coordinator(db):
    return grant_labs_role(UserFactory(), "coord")


@pytest.fixture()
def client(coordinator):
    api = APIClient()
    api.force_authenticate(user=coordinator)
    return api


def get(client, **params):
    params = {"start_date": DAY.isoformat(), "end_date": DAY.isoformat(), **params}
    return client.get(URL, params)


@pytest.mark.django_db
def test_plain_lab_user_is_denied():
    api = APIClient()
    api.force_authenticate(user=grant_labs_role(UserFactory(), "user"))
    assert api.get(URL, {"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}).status_code == 403


@pytest.mark.django_db
def test_date_range_is_required_and_bounded(client):
    assert client.get(URL).status_code == 400
    assert get(client, end_date=(DAY - timedelta(days=1)).isoformat()).status_code == 400
    assert get(client, end_date=(DAY + timedelta(days=366)).isoformat()).status_code == 400


@pytest.mark.django_db
def test_lists_sessions_in_range_newest_first_with_links(client):
    bench = BenchFactory()
    user = UserFactory(username="alice")
    early = session(
        hour=8,
        bench=bench,
        user=user,
        active_duration_seconds=1800,
        booking_code="BK-1",
        access_type=SessionAccessType.BOOKED,
    )
    late = session(hour=15)
    session(day=DAY - timedelta(days=1))  # outside the range
    session(day=DAY + timedelta(days=1))  # outside the range

    response = get(client)

    assert response.status_code == 200
    rows = response.json()["data"]
    assert [row["id"] for row in rows] == [late.id, early.id]
    first = rows[1]
    assert first["duration_minutes"] == 60.0
    assert first["active_minutes"] == 30.0
    assert first["bench"]["id"] == bench.id
    assert first["user"]["username"] == "alice"
    assert first["computer"]["id"] == early.computing_equipment_id
    assert first["access_type"] == {"value": "booked", "label": "Booked"}
    assert first["booking_code"] == "BK-1"
    assert response.json()["meta"]["pagination"]["count"] == 2


@pytest.mark.django_db
def test_filters_and_search(client):
    bench = BenchFactory()
    on_bench = session(bench=bench, remote_user="bob", access_type=SessionAccessType.AD_HOC)
    session(remote_user="carol", access_type=SessionAccessType.BOOKED, booking_code="BK-2")

    assert [r["id"] for r in get(client, bench_id=bench.id).json()["data"]] == [on_bench.id]
    assert [r["id"] for r in get(client, q="bob").json()["data"]] == [on_bench.id]
    assert [r["id"] for r in get(client, access_type="ad_hoc").json()["data"]] == [on_bench.id]
    assert [r["id"] for r in get(client, computer_id=on_bench.computing_equipment_id).json()["data"]] == [on_bench.id]


@pytest.mark.django_db
def test_ordering_is_stable_with_id_tie_breaker(client):
    first = session(hour=10)
    second = session(hour=10)
    assert [r["id"] for r in get(client).json()["data"]] == [second.id, first.id]
    assert [r["id"] for r in get(client, ordering="login_time").json()["data"]] == [first.id, second.id]
    assert get(client, ordering="remote_ip").status_code == 400


@pytest.mark.django_db
def test_page_query_count_does_not_grow_with_rows(client):
    for hour in range(8, 18):
        session(hour=hour, bench=BenchFactory(), user=UserFactory())
    get(client)  # warm the per-request role lookup so both measurements compare the same work
    with CaptureQueriesContext(connection) as small:
        get(client, page_size=2)
    with CaptureQueriesContext(connection) as large:
        get(client, page_size=10)
    assert len(large.captured_queries) == len(small.captured_queries)
