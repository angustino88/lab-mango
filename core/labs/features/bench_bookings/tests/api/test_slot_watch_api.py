"""HTTP tests for /api/labs/bench-slot-watches: ownership, contract shape and status codes."""

from datetime import timedelta

import pytest
from rest_framework.test import APIClient

from core.labs.models import BenchSlotWatch
from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

URL = "/api/labs/bench-slot-watches"
H = timedelta(hours=1)


def _payload(bench, now, **extra):
    return {
        "bench_id": bench.pk,
        "starts_at": (now + H).isoformat(),
        "ends_at": (now + 3 * H).isoformat(),
        **extra,
    }


@pytest.mark.django_db
class TestSlotWatchAPI:
    def test_anonymous_is_rejected(self, bench, now):
        assert APIClient().post(URL, _payload(bench, now), format="json").status_code in (401, 403)

    def test_create_list_detail_cancel(self, api_client, bench, now):
        created = api_client.post(URL, _payload(bench, now), format="json")
        assert created.status_code == 201, created.content
        body = created.json()["data"]
        assert body["bench"]["id"] == bench.pk
        assert body["status"]["value"] == "active"
        assert "channels" not in body  # the server decides delivery channels

        listed = api_client.get(URL)
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["data"]] == [body["id"]]

        detail = api_client.get(f"{URL}/{body['id']}")
        assert detail.status_code == 200

        cancelled = api_client.post(f"{URL}/{body['id']}/actions/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"]["value"] == "cancelled"
        assert api_client.get(URL, {"status": "active"}).json()["data"] == []

    def test_repeat_create_returns_same_watch(self, api_client, bench, now):
        first = api_client.post(URL, _payload(bench, now), format="json").json()["data"]
        second = api_client.post(URL, _payload(bench, now), format="json").json()["data"]
        assert first["id"] == second["id"]
        assert BenchSlotWatch.objects.count() == 1

    def test_invalid_range_is_422(self, api_client, bench, now):
        response = api_client.post(
            URL,
            {"bench_id": bench.pk, "starts_at": (now + 3 * H).isoformat(), "ends_at": (now + H).isoformat()},
            format="json",
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "slot_watch_invalid"

    def test_unknown_bench_is_404(self, api_client, now):
        response = api_client.post(
            URL,
            {"bench_id": 999999, "starts_at": (now + H).isoformat(), "ends_at": (now + 2 * H).isoformat()},
            format="json",
        )
        assert response.status_code == 404

    def test_other_users_watch_is_invisible(self, api_client, bench, now):
        watch_id = api_client.post(URL, _payload(bench, now), format="json").json()["data"]["id"]
        stranger = APIClient()
        stranger.force_authenticate(grant_labs_role(UserFactory(username="slot-stranger"), "member"))
        assert stranger.get(f"{URL}/{watch_id}").status_code == 404
        assert stranger.post(f"{URL}/{watch_id}/actions/cancel").status_code == 404
        assert stranger.get(URL).json()["data"] == []
        assert BenchSlotWatch.objects.get(pk=watch_id).status == "active"

    def test_follow_action(self, bench, now):
        from core.labs.models import BenchBooking

        owner = grant_labs_role(UserFactory(username="slot-owner"), "member")
        booking = BenchBooking(bench=bench, starts_at=now + H, ends_at=now + 2 * H, booking_code="FOLLOW-API-1")
        booking.save(actor=owner)
        follower = APIClient()
        follower.force_authenticate(grant_labs_role(UserFactory(username="slot-follower"), "member"))
        response = follower.post(f"/api/labs/bench-bookings/{booking.pk}/actions/follow")
        assert response.status_code == 200, response.content
        assert response.json()["data"]["followed_booking_id"] == booking.pk
        owner_client = APIClient()
        owner_client.force_authenticate(owner)
        own = owner_client.post(f"/api/labs/bench-bookings/{booking.pk}/actions/follow")
        assert own.status_code == 422 and own.json()["error"]["code"] == "slot_watch_own_booking"
        assert follower.post("/api/labs/bench-bookings/999999/actions/follow").status_code == 404
