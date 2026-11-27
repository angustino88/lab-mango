"""POST /api/labs/bench-bookings/actions/check: a preview that writes nothing."""

from datetime import datetime, timedelta

import pytest
from rest_framework.test import APIClient

from core.labs.models import BenchBooking, BookingApprovalStatus, BookingStatus, ResourceDowntime
from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

URL = "/api/labs/bench-bookings/actions/check"


def _body(bench, project, starts_at, ends_at, **extra):
    return {
        "bench_id": bench.pk,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "project_id": project.pk,
        "reason": "Firmware validation",
        **extra,
    }


def _codes(result):
    return [problem["code"] for problem in result["problems"]]


@pytest.mark.django_db
class TestNewBooking:
    def test_free_bench_is_bookable_and_nothing_is_written(self, api_client, bench, project, future_window):
        response = api_client.post(URL, _body(bench, project, *future_window), format="json")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["can_book_all"] is True
        assert data["results"][0]["is_bookable"] is True
        assert data["results"][0]["approval_status"]["value"] == BookingApprovalStatus.APPROVED
        assert data["results"][0]["problems"] == []
        assert not BenchBooking.objects.exists()

    def test_overlap_reports_the_create_conflict_code(self, api_client, bench, project, future_window, make_booking):
        make_booking(starts_at=future_window[0], ends_at=future_window[1])

        check = api_client.post(URL, _body(bench, project, *future_window), format="json")
        create = api_client.post("/api/labs/bench-bookings", _body(bench, project, *future_window), format="json")

        result = check.json()["data"]["results"][0]
        assert check.status_code == 200
        assert result["is_bookable"] is False
        assert _codes(result) == ["bench_booking_conflict"]
        assert create.status_code == 409
        assert create.json()["error"]["code"] == "bench_booking_conflict"

    def test_long_booking_needs_approval(self, api_client, bench, project, now):
        response = api_client.post(
            URL, _body(bench, project, now + timedelta(hours=1), now + timedelta(hours=6)), format="json"
        )

        result = response.json()["data"]["results"][0]
        assert result["is_bookable"] is True
        assert result["approval_status"]["value"] == BookingApprovalStatus.PENDING

    def test_invalid_period_lists_field_problem(self, api_client, bench, project, now):
        starts_at = now + timedelta(hours=2)

        response = api_client.post(
            URL, _body(bench, project, starts_at, starts_at + timedelta(minutes=5)), format="json"
        )

        result = response.json()["data"]["results"][0]
        assert result["is_bookable"] is False
        assert result["problems"] == [
            {"code": "invalid", "field": "ends_at", "message": "Minimum booking duration is 10 minutes."}
        ]

    def test_downtime_blocks(self, api_client, bench, project, future_window):
        ResourceDowntime.for_new_resource(bench, condition="out_of_service", starts_at=future_window[0]).save()

        response = api_client.post(URL, _body(bench, project, *future_window), format="json")

        assert _codes(response.json()["data"]["results"][0]) == ["bench_booking_conflict"]

    def test_series_checks_each_period(self, api_client, bench, project, now, make_booking):
        first = (now + timedelta(days=1), now + timedelta(days=1, hours=2))
        second = (now + timedelta(days=8), now + timedelta(days=8, hours=2))
        make_booking(starts_at=second[0], ends_at=second[1])
        body = {
            "bench_id": bench.pk,
            "project_id": project.pk,
            "occurrences": [{"starts_at": s.isoformat(), "ends_at": e.isoformat()} for s, e in (first, second)],
        }

        response = api_client.post(URL, body, format="json")

        results = response.json()["data"]["results"]
        assert response.status_code == 200
        assert [result["is_bookable"] for result in results] == [True, False]
        assert response.json()["data"]["can_book_all"] is False

    def test_series_is_limited_to_ten(self, api_client, bench, project, now):
        period = {
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, hours=1)).isoformat(),
        }

        response = api_client.post(
            URL, {"bench_id": bench.pk, "project_id": project.pk, "occurrences": [period] * 11}, format="json"
        )

        assert response.status_code in (400, 422)

    def test_missing_bench_is_a_request_error(self, api_client, project, future_window):
        response = api_client.post(
            URL,
            {
                "starts_at": future_window[0].isoformat(),
                "ends_at": future_window[1].isoformat(),
                "project_id": project.pk,
            },
            format="json",
        )

        assert response.status_code in (400, 422)

    def test_unknown_field_is_refused(self, api_client, bench, project, future_window):
        response = api_client.post(URL, _body(bench, project, *future_window, hold_bench=True), format="json")

        assert response.status_code in (400, 422)

    def test_anonymous_is_refused(self, bench, project, future_window):
        response = APIClient().post(URL, _body(bench, project, *future_window), format="json")

        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestChange:
    def test_moving_own_booking_ignores_itself(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)

        response = api_client.post(
            URL, {"booking_id": booking.pk, "ends_at": (ends_at + timedelta(minutes=30)).isoformat()}, format="json"
        )

        result = response.json()["data"]["results"][0]
        assert response.status_code == 200
        assert result["is_bookable"] is True

    def test_cancelled_booking_cannot_change(self, api_client, make_booking, future_window):
        booking = make_booking(starts_at=future_window[0], ends_at=future_window[1], status=BookingStatus.CANCELLED)

        response = api_client.post(URL, {"booking_id": booking.pk, "reason": "x"}, format="json")

        assert _codes(response.json()["data"]["results"][0]) == ["bench_booking_conflict"]

    def test_lengthening_past_threshold_needs_approval(self, api_client, make_booking, future_window):
        starts_at, _ = future_window
        booking = make_booking(starts_at=starts_at, ends_at=starts_at + timedelta(hours=1))

        response = api_client.post(
            URL, {"booking_id": booking.pk, "ends_at": (starts_at + timedelta(hours=5)).isoformat()}, format="json"
        )

        assert response.json()["data"]["results"][0]["approval_status"]["value"] == BookingApprovalStatus.PENDING

    def test_other_users_booking_is_hidden_or_forbidden(self, bench, make_booking, future_window):
        booking = make_booking(starts_at=future_window[0], ends_at=future_window[1])
        stranger = APIClient()
        stranger.force_authenticate(user=grant_labs_role(UserFactory(username="check-stranger"), "member"))

        response = stranger.post(URL, {"booking_id": booking.pk}, format="json")

        assert response.status_code in (403, 404)

    def test_series_is_only_for_new_bookings(self, api_client, make_booking, future_window):
        booking = make_booking(starts_at=future_window[0], ends_at=future_window[1])
        period = {"starts_at": future_window[0].isoformat(), "ends_at": future_window[1].isoformat()}

        response = api_client.post(URL, {"booking_id": booking.pk, "occurrences": [period]}, format="json")

        assert response.status_code == 422


@pytest.mark.django_db
class TestAlternatives:
    def test_busy_bench_suggests_other_bench_and_next_free_slot(
        self, api_client, bench, other_bench, project, future_window, make_booking
    ):
        starts_at, ends_at = future_window
        make_booking(starts_at=starts_at, ends_at=ends_at)

        response = api_client.post(
            URL, _body(bench, project, *future_window, suggest_alternatives=True), format="json"
        )

        alternatives = response.json()["data"]["results"][0]["alternatives"]
        assert [item["bench"]["id"] for item in alternatives] == [other_bench.pk, bench.pk]
        assert alternatives[0]["starts_at"] == response.json()["data"]["results"][0]["starts_at"]
        same_bench = alternatives[1]
        assert datetime.fromisoformat(same_bench["starts_at"]) == ends_at

    def test_bookable_period_gets_no_alternatives(self, api_client, bench, project, future_window):
        response = api_client.post(
            URL, _body(bench, project, *future_window, suggest_alternatives=True), format="json"
        )

        assert response.json()["data"]["results"][0]["alternatives"] == []

    def test_alternatives_are_off_by_default(
        self, api_client, bench, other_bench, project, future_window, make_booking
    ):
        make_booking(starts_at=future_window[0], ends_at=future_window[1])

        response = api_client.post(URL, _body(bench, project, *future_window), format="json")

        assert response.json()["data"]["results"][0]["alternatives"] == []

    def test_change_does_not_count_its_own_slot_as_busy(self, api_client, bench, make_booking, future_window, now):
        starts_at, ends_at = future_window
        own = make_booking(starts_at=starts_at, ends_at=ends_at)
        make_booking(starts_at=ends_at, ends_at=ends_at + timedelta(hours=1))

        response = api_client.post(
            URL,
            {
                "booking_id": own.pk,
                "ends_at": (ends_at + timedelta(minutes=30)).isoformat(),
                "suggest_alternatives": True,
            },
            format="json",
        )

        result = response.json()["data"]["results"][0]
        assert result["is_bookable"] is False
        same_bench = [item for item in result["alternatives"] if item["bench"]["id"] == bench.pk]
        assert same_bench and same_bench[0]["starts_at"].startswith(starts_at.date().isoformat())
