"""GET /api/labs/benches/availability: free benches and busy time in a window."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.labs.features.bench_bookings.tests.conftest import place_computer
from core.labs.models import Bench, BenchFavorite, BookingStatus, DowntimeBookingAccess, ResourceDowntime
from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

URL = "/api/labs/benches/availability"


@pytest.fixture()
def window(now):
    starts_at = (now + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    return starts_at, starts_at + timedelta(hours=4)


def _get(client, window, **params):
    starts_at, ends_at = window
    return client.get(URL, {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(), **params})


def _names(response):
    return [item["bench"]["name"] for item in response.json()["data"]["benches"]]


@pytest.mark.django_db
class TestAvailability:
    def test_free_bench_is_listed_with_one_free_period(self, api_client, bench, window):
        response = _get(api_client, window)

        assert response.status_code == 200
        data = response.json()["data"]
        item = data["benches"][0]
        assert item["bench"]["id"] == bench.pk
        assert item["is_fully_free"] is True
        assert item["has_computing"] is True
        assert item["busy_periods"] == []
        assert len(item["free_periods"]) == 1
        assert data["is_truncated"] is False

    def test_booked_bench_is_left_out_by_default(self, api_client, bench, other_bench, window, make_booking):
        make_booking(starts_at=window[0] + timedelta(hours=1), ends_at=window[0] + timedelta(hours=2))

        assert _names(_get(api_client, window)) == [other_bench.name]

    def test_any_free_shows_busy_time_without_holder(self, api_client, bench, window, make_booking):
        make_booking(starts_at=window[0] + timedelta(hours=1), ends_at=window[0] + timedelta(hours=2))

        response = _get(api_client, window, mode="any_free", bench_id=str(bench.pk))

        item = response.json()["data"]["benches"][0]
        assert item["is_fully_free"] is False
        assert item["busy_periods"] == [
            {
                "starts_at": item["busy_periods"][0]["starts_at"],
                "ends_at": item["busy_periods"][0]["ends_at"],
                "reason": {"value": "booking", "label": "Booked"},
            }
        ]
        assert set(item["busy_periods"][0]) == {"starts_at", "ends_at", "reason"}
        assert len(item["free_periods"]) == 2
        assert item["next_free_at"] == item["free_periods"][0]["starts_at"]

    def test_min_free_minutes_filters_short_gaps(self, api_client, bench, window, make_booking):
        make_booking(starts_at=window[0] + timedelta(minutes=30), ends_at=window[1] - timedelta(minutes=30))

        short = _get(api_client, window, mode="any_free", min_free_minutes=60, bench_id=str(bench.pk))
        ok = _get(api_client, window, mode="any_free", min_free_minutes=30, bench_id=str(bench.pk))

        assert _names(short) == []
        assert _names(ok) == [bench.name]

    def test_cancelled_booking_is_not_busy(self, api_client, bench, window, make_booking):
        make_booking(starts_at=window[0], ends_at=window[1], status=BookingStatus.CANCELLED)

        assert bench.name in _names(_get(api_client, window))

    def test_downtime_is_busy(self, api_client, bench, window):
        ResourceDowntime.for_new_resource(bench, condition="out_of_service", starts_at=window[0]).save()

        response = _get(api_client, window, mode="any_free", bench_id=str(bench.pk))

        assert _names(response) == []

    def test_operator_only_downtime_is_free_for_operators(self, bench, window):
        downtime = ResourceDowntime.for_new_resource(bench, condition="in_maintenance", starts_at=window[0])
        downtime.booking_access = DowntimeBookingAccess.LAB_OPERATORS
        downtime.save()
        member, operator = APIClient(), APIClient()
        member.force_authenticate(user=grant_labs_role(UserFactory(username="avail-member"), "member"))
        operator.force_authenticate(user=grant_labs_role(UserFactory(username="avail-operator"), "coord"))

        assert _names(_get(member, window, bench_id=str(bench.pk))) == []
        assert _names(_get(operator, window, bench_id=str(bench.pk))) == [bench.name]

    def test_retired_bench_is_never_listed(self, api_client, bench, window):
        Bench.objects.filter(pk=bench.pk).update(lifecycle_status="retired")

        assert bench.name not in _names(_get(api_client, window))

    def test_has_computing_filter(self, api_client, bench, window):
        Bench.objects.create(sku="BB-NO-PC", name="No computer")

        assert _names(_get(api_client, window, has_computing="false")) == ["No computer"]

    def test_favorites_rank_first(self, api_client, actor, bench, other_bench, window):
        BenchFavorite.objects.create(user=actor, bench=other_bench)

        assert _names(_get(api_client, window))[:2] == [other_bench.name, bench.name]

    def test_limit_marks_truncation(self, api_client, bench, other_bench, window):
        response = _get(api_client, window, limit=1)

        assert len(response.json()["data"]["benches"]) == 1
        assert response.json()["data"]["is_truncated"] is True

    def test_query_count_does_not_grow_with_benches(self, api_client, bench, window):
        _get(api_client, window)  # warm the role and content-type caches
        with CaptureQueriesContext(connection) as few:
            _get(api_client, window)
        for index in range(5):
            place_computer(
                Bench.objects.create(sku=f"BB-MANY-{index}", name=f"Many {index}"), sku=f"BB-MANY-PC-{index}"
            )
        with CaptureQueriesContext(connection) as many:
            _get(api_client, window)

        assert len(many) == len(few)

    @pytest.mark.parametrize(
        "params",
        [
            {"ends_at": "2026-01-01T00:00:00Z", "starts_at": "2026-01-02T00:00:00Z"},
            {"starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-20T00:00:00Z"},
            {"starts_at": "2026-01-01", "ends_at": "2026-01-02T00:00:00Z"},
            {"starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-02T00:00:00Z", "min_free_minutes": "30"},
        ],
    )
    def test_bad_value_is_400(self, api_client, params):
        response = api_client.get(URL, params)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_failed"

    def test_unknown_parameter_is_400(self, api_client):
        response = api_client.get(
            URL, {"starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-02T00:00:00Z", "unknown": "1"}
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_query"

    def test_anonymous_is_refused(self, window):
        assert _get(APIClient(), window).status_code in (401, 403)
