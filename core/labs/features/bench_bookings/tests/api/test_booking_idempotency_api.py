"""Optional Idempotency-Key on bench booking create, update and cancel (response standard RW-6)."""

import uuid
from datetime import timedelta

import pytest
from rest_framework.test import APIClient

from core.labs.models import BenchBooking, BenchBookingWriteReceipt, BookingStatus
from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

URL = "/api/labs/bench-bookings"


def _key_headers(key=None):
    return {"HTTP_IDEMPOTENCY_KEY": key or str(uuid.uuid4())}


def _create_body(bench, project, starts_at, ends_at, reason="Firmware validation"):
    return {
        "bench_id": bench.pk,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "reason": reason,
        "project_id": project.pk,
    }


@pytest.mark.django_db
class TestCreate:
    def test_same_key_replays_first_response_and_creates_one_booking(self, api_client, bench, project, future_window):
        body = _create_body(bench, project, *future_window)
        headers = _key_headers()

        first = api_client.post(URL, body, format="json", **headers)
        replay = api_client.post(URL, body, format="json", **headers)

        assert first.status_code == replay.status_code == 201
        assert first.json() == replay.json()
        assert first["Location"] == replay["Location"]
        assert "Idempotency-Replayed" not in first
        assert replay["Idempotency-Replayed"] == "true"
        assert BenchBooking.objects.count() == 1
        assert BenchBookingWriteReceipt.objects.get().response_body == first.json()

    def test_same_key_with_different_body_is_refused(self, api_client, bench, project, future_window):
        headers = _key_headers()
        api_client.post(URL, _create_body(bench, project, *future_window), format="json", **headers)

        mismatch = api_client.post(
            URL, _create_body(bench, project, *future_window, reason="Other"), format="json", **headers
        )

        assert mismatch.status_code == 422
        assert mismatch.json()["error"]["code"] == "idempotency_key_reuse"
        assert BenchBooking.objects.count() == 1

    def test_without_key_nothing_changes(self, api_client, bench, project, future_window):
        response = api_client.post(URL, _create_body(bench, project, *future_window), format="json")

        assert response.status_code == 201
        assert "Idempotency-Replayed" not in response
        assert not BenchBookingWriteReceipt.objects.exists()

    def test_invalid_key_is_refused(self, api_client, bench, project, future_window):
        response = api_client.post(
            URL, _create_body(bench, project, *future_window), format="json", **_key_headers("not-a-uuid")
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_idempotency_key"
        assert not BenchBooking.objects.exists()

    def test_failed_write_stores_nothing_and_key_can_be_retried(
        self, api_client, bench, project, future_window, make_booking
    ):
        starts_at, ends_at = future_window
        blocker = make_booking(starts_at=starts_at, ends_at=ends_at)
        headers = _key_headers()
        body = _create_body(bench, project, starts_at, ends_at)

        refused = api_client.post(URL, body, format="json", **headers)
        blocker.status = BookingStatus.CANCELLED
        blocker.cancellation_reason = "Freed for the retry"
        blocker.save()
        retried = api_client.post(URL, body, format="json", **headers)

        assert refused.status_code == 409
        assert retried.status_code == 201
        assert BenchBookingWriteReceipt.objects.count() == 1

    def test_keys_are_scoped_per_user(self, api_client, bench, other_bench, project, future_window):
        other = APIClient()
        other.force_authenticate(user=grant_labs_role(UserFactory(username="idempotency-other-user"), "member"))
        key = str(uuid.uuid4())

        first = api_client.post(URL, _create_body(bench, project, *future_window), format="json", **_key_headers(key))
        second = other.post(
            URL, _create_body(other_bench, project, *future_window), format="json", **_key_headers(key)
        )

        assert first.status_code == second.status_code == 201
        assert first.json()["data"]["id"] != second.json()["data"]["id"]


@pytest.mark.django_db
class TestUpdateAndCancel:
    def test_update_replays(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        headers = _key_headers()
        body = {"ends_at": (ends_at + timedelta(minutes=30)).isoformat()}

        first = api_client.patch(f"{URL}/{booking.pk}", body, format="json", **headers)
        replay = api_client.patch(f"{URL}/{booking.pk}", body, format="json", **headers)

        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()
        assert replay["Idempotency-Replayed"] == "true"

    def test_key_reused_for_another_booking_is_refused(self, api_client, make_booking, future_window, other_bench):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        other = make_booking(starts_at=starts_at, ends_at=ends_at, bench_obj=other_bench)
        headers = _key_headers()
        body = {"reason": "Same body"}

        api_client.patch(f"{URL}/{booking.pk}", body, format="json", **headers)
        reused = api_client.patch(f"{URL}/{other.pk}", body, format="json", **headers)

        assert reused.status_code == 422
        assert reused.json()["error"]["code"] == "idempotency_key_reuse"

    def test_key_reused_for_another_operation_is_refused(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        headers = _key_headers()

        api_client.patch(f"{URL}/{booking.pk}", {"reason": "Updated"}, format="json", **headers)
        cancel = api_client.post(f"{URL}/{booking.pk}/actions/cancel", {}, format="json", **headers)

        assert cancel.status_code == 422
        booking.refresh_from_db()
        assert booking.status == BookingStatus.RESERVED

    def test_cancel_replays(self, api_client, make_booking, future_window):
        booking = make_booking(starts_at=future_window[0], ends_at=future_window[1])
        headers = _key_headers()
        url = f"{URL}/{booking.pk}/actions/cancel"

        first = api_client.post(url, {"reason": "Plans changed"}, format="json", **headers)
        replay = api_client.post(url, {"reason": "Plans changed"}, format="json", **headers)

        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()
        assert replay["Idempotency-Replayed"] == "true"
        assert first.json()["data"]["status"]["value"] == BookingStatus.CANCELLED

    def test_cancel_by_code_replays(self, api_client, make_booking, future_window):
        booking = make_booking(starts_at=future_window[0], ends_at=future_window[1], code="BOOKING-IDEM-0001")
        headers = _key_headers()
        url = f"{URL}/code/{booking.booking_code}/actions/cancel"

        first = api_client.post(url, {}, format="json", **headers)
        replay = api_client.post(url, {}, format="json", **headers)

        assert first.status_code == replay.status_code == 200
        assert replay["Idempotency-Replayed"] == "true"
