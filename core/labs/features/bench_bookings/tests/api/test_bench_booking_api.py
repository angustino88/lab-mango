"""HTTP tests for bench booking endpoints: auth, contract shape and status codes."""

from datetime import timedelta
from unittest.mock import patch
import uuid

import pytest
from rest_framework.test import APIClient

from core.labs.models import BenchBooking, BookingApprovalStatus
from core.users.public import LabsRole
from core.users.models import URSGroup
from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"
URL = "/api/labs/bench-bookings"
VALID_REASON = "Test booking"


def _detail(booking_id):
    return f"/api/labs/bench-bookings/{booking_id}"


def _detail_by_code(booking_code):
    return f"/api/labs/bench-bookings/code/{booking_code}"


def _approval_action(booking_id, action):
    return f"/api/labs/bench-bookings/{booking_id}/actions/{action}"


def _idempotency_headers(key=None):
    return {"HTTP_IDEMPOTENCY_KEY": key or str(uuid.uuid4())}


def _grant_role(user, role):
    group = user.groups.create(name=f"api-approval-{role.value}-{user.pk}")
    URSGroup.objects.create(group=group, urs_group_id=200000 + user.pk, labs_role=role.value)
    return user


@pytest.mark.django_db
class TestAuthentication:
    def test_anonymous_request_is_rejected(self, bench, future_window):
        starts_at, ends_at = future_window
        response = APIClient().post(
            URL,
            {
                "bench_id": bench.pk,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "reason": VALID_REASON,
            },
            format="json",
        )
        assert response.status_code in (401, 403)

    def test_api_key_alone_is_sufficient(self, bench, project, future_window):
        starts_at, ends_at = future_window
        with patch(_PATCH_APIKEY, return_value=True):
            response = APIClient().post(
                URL,
                {
                    "bench_id": bench.pk,
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat(),
                    "reason": VALID_REASON,
                    "project_id": project.pk,
                },
                format="json",
            )
        assert response.status_code == 201

    def test_authenticated_user_without_api_key_is_sufficient(self, api_client, bench, project, future_window):
        starts_at, ends_at = future_window
        with patch(_PATCH_APIKEY, return_value=False):
            response = api_client.post(
                URL,
                {
                    "bench_id": bench.pk,
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat(),
                    "reason": VALID_REASON,
                    "project_id": project.pk,
                },
                format="json",
            )
        assert response.status_code == 201


@pytest.mark.django_db
class TestCreateEndpoint:
    def test_create_requires_reason_and_project(self, api_client, bench, future_window):
        starts_at, ends_at = future_window
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                URL,
                {"bench_id": bench.pk, "starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()},
                format="json",
            )
        assert response.status_code in (400, 422)

    def test_create_returns_201_with_booking(self, api_client, bench, project, future_window):
        starts_at, ends_at = future_window
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                URL,
                {
                    "bench_id": bench.pk,
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat(),
                    "reason": VALID_REASON,
                    "project_id": project.pk,
                },
                format="json",
            )
        assert response.status_code == 201
        body = response.json()["data"]
        assert body["bench"]["id"] == bench.pk
        assert body["status"] == {"value": "reserved", "label": "Reserved"}
        assert body["project"]["id"] == project.pk
        assert "created_at" in body
        assert "updated_at" in body
        assert "created" not in body
        assert "modified" not in body
        assert body["booking_code"].startswith("BOOKING-")

    def test_conflict_returns_409(self, api_client, bench, project, make_booking, future_window):
        starts_at, ends_at = future_window
        make_booking(starts_at=starts_at, ends_at=ends_at)
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                URL,
                {
                    "bench_id": bench.pk,
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat(),
                    "reason": VALID_REASON,
                    "project_id": project.pk,
                },
                format="json",
            )
        assert response.status_code == 409

    def test_invalid_period_returns_400(self, api_client, bench, project, future_window):
        starts_at, _ = future_window
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                URL,
                {
                    "bench_id": bench.pk,
                    "starts_at": starts_at.isoformat(),
                    "ends_at": starts_at.isoformat(),
                    "reason": VALID_REASON,
                    "project_id": project.pk,
                },
                format="json",
            )
        assert response.status_code in (400, 422)


@pytest.mark.django_db
class TestGetAndUpdateEndpoints:
    def test_get_returns_booking(self, api_client, bench, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.get(_detail(booking.pk))
        assert response.status_code == 200
        assert response.json()["data"]["id"] == booking.pk

    def test_get_unknown_returns_404(self, api_client):
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.get(_detail(999999))
        assert response.status_code == 404

    def test_get_by_code_returns_booking(self, api_client, bench, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at, code="BOOKING-DETAILCODE")
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.get(_detail_by_code(booking.booking_code))
        assert response.status_code == 200
        assert response.json()["data"]["id"] == booking.pk

    @pytest.mark.parametrize("route", ["id", "code"])
    def test_other_user_cannot_read_booking_detail(self, make_booking, future_window, route):
        # Regression: detail returned any booking to any authenticated user while the list
        # was scoped to the creator; ids are sequential, so bookings were enumerable.
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at, code="BOOKING-PRIVATE01")
        client = APIClient()
        client.force_authenticate(user=grant_labs_role(UserFactory(username="booking-detail-outsider"), "user"))
        url = _detail(booking.pk) if route == "id" else _detail_by_code(booking.booking_code)

        response = client.get(url)

        assert response.status_code == 404  # no existence oracle

    @pytest.mark.parametrize("route", ["id", "code"])
    def test_api_key_only_caller_cannot_read_booking_detail(self, make_booking, future_window, route):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at, code="BOOKING-PRIVATE02")
        url = _detail(booking.pk) if route == "id" else _detail_by_code(booking.booking_code)

        with patch(_PATCH_APIKEY, return_value=True):
            response = APIClient().get(url)

        assert response.status_code == 404  # same scope as the list: no user, no rows

    def test_coordinator_can_read_any_booking_detail(self, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        coordinator = _grant_role(UserFactory(username="booking-detail-coordinator"), LabsRole.COORDINATOR)
        client = APIClient()
        grant_labs_role(coordinator, "user")
        client.force_authenticate(user=coordinator)

        response = client.get(_detail(booking.pk))

        assert response.status_code == 200
        assert response.json()["data"]["id"] == booking.pk

    def test_patch_by_code_updates_booking(self, api_client, bench, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at, code="BOOKING-UPDATECODE")
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.patch(_detail_by_code(booking.booking_code), {"reason": "Updated"}, format="json")
        assert response.status_code == 200
        assert response.json()["data"]["reason"] == "Updated"

    def test_patch_in_progress_start_returns_409(self, api_client, bench, make_booking, now):
        from core.labs.models import BookingStatus

        booking = make_booking(
            starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(hours=1), status=BookingStatus.IN_PROGRESS
        )
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.patch(
                _detail(booking.pk), {"starts_at": (now - timedelta(minutes=2)).isoformat()}, format="json"
            )
        assert response.status_code == 409

    def test_patch_cannot_change_booking_status(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.patch(_detail(booking.pk), {"status": "cancelled"}, format="json")
        assert response.status_code == 422

    def test_cancel_action_endpoint(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.post(
                f"/api/labs/bench-bookings/{booking.pk}/actions/cancel",
                {"reason": "User cancelled"},
                format="json",
            )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == {"value": "cancelled", "label": "Cancelled"}
        stored = BenchBooking.objects.get(pk=booking.pk)
        assert stored.cancellation_reason == "User cancelled"
        assert stored.reason != "User cancelled"  # the booking purpose is not overwritten

    def test_patch_rejects_expired_status(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.patch(_detail(booking.pk), {"status": "expired"}, format="json")
        assert response.status_code in (400, 422)


@pytest.mark.django_db
class TestBookingApprovalActions:
    def test_coordinator_can_approve_pending_booking(self, actor, make_booking, now):
        coordinator = _grant_role(UserFactory(username="api-booking-coordinator"), LabsRole.COORDINATOR)
        booking = make_booking(
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=7),
        )
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        client = APIClient()
        grant_labs_role(coordinator, "user")
        client.force_authenticate(user=coordinator)

        response = client.post(
            _approval_action(booking.pk, "approve"), {}, format="json", **_idempotency_headers()
        )

        assert response.status_code == 200
        assert response.json()["data"]["approval_status"]["value"] == "approved"
        booking.refresh_from_db()
        assert booking.approved_by_id == coordinator.pk

    def test_admin_can_reject_with_reason(self, make_booking, now):
        admin = _grant_role(UserFactory(username="api-booking-admin"), LabsRole.ADMIN)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        client = APIClient()
        grant_labs_role(admin, "user")
        client.force_authenticate(user=admin)

        response = client.post(
            _approval_action(booking.pk, "reject"),
            {"reason": "Incomplete request"},
            format="json",
            **_idempotency_headers(),
        )

        assert response.status_code == 200
        assert response.json()["data"]["approval_status"]["value"] == "rejected"
        booking.refresh_from_db()
        assert booking.rejection_reason == "Incomplete request"

    def test_regular_user_cannot_approve_booking(self, api_client, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()

        response = api_client.post(
            _approval_action(booking.pk, "approve"), {}, format="json", **_idempotency_headers()
        )

        assert response.status_code == 403
        booking.refresh_from_db()
        assert booking.approval_status == BookingApprovalStatus.PENDING

    def test_api_key_only_cannot_approve_booking(self, make_booking, now):
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        response = APIClient().post(
            _approval_action(booking.pk, "approve"), {}, format="json", **_idempotency_headers()
        )

        assert response.status_code == 401
        booking.refresh_from_db()
        assert booking.approval_status == BookingApprovalStatus.PENDING

    def test_reject_requires_nonblank_reason(self, actor, make_booking, now):
        coordinator = _grant_role(UserFactory(username="api-booking-coordinator-empty-reason"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        client = APIClient()
        grant_labs_role(coordinator, "user")
        client.force_authenticate(user=coordinator)

        response = client.post(
            _approval_action(booking.pk, "reject"),
            {"reason": "   "},
            format="json",
            **_idempotency_headers(),
        )

        assert response.status_code == 422
        booking.refresh_from_db()
        assert booking.approval_status == BookingApprovalStatus.PENDING

    def test_approve_requires_a_valid_uuid_key(self, actor, make_booking, now):
        coordinator = _grant_role(UserFactory(username="api-booking-coordinator-missing-key"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        client = APIClient()
        grant_labs_role(coordinator, "user")
        client.force_authenticate(user=coordinator)

        missing = client.post(_approval_action(booking.pk, "approve"), {}, format="json")
        invalid = client.post(
            _approval_action(booking.pk, "approve"),
            {},
            format="json",
            **_idempotency_headers("invalid"),
        )

        assert missing.status_code == 400
        assert missing.json()["error"]["code"] == "idempotency_key_required"
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "invalid_idempotency_key"
        assert booking.approval_status == BookingApprovalStatus.PENDING

    def test_same_key_replays_exact_approve_response(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="api-booking-coordinator-replay"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        client = APIClient()
        grant_labs_role(coordinator, "user")
        client.force_authenticate(user=coordinator)
        headers = _idempotency_headers()
        url = _approval_action(booking.pk, "approve")

        first = client.post(url, {}, format="json", **headers)
        replay = client.post(url, {}, format="json", **headers)

        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()
        assert "Idempotency-Replayed" not in first
        assert replay["Idempotency-Replayed"] == "true"
        assert booking.decision_receipts.count() == 1
        assert booking.decision_receipts.get().response_body == first.json()

    def test_same_key_with_different_rejection_reason_conflicts(self, make_booking, now):
        coordinator = _grant_role(UserFactory(username="api-booking-coordinator-mismatch"), LabsRole.COORDINATOR)
        booking = make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=7))
        booking.approval_status = BookingApprovalStatus.PENDING
        booking.save()
        client = APIClient()
        grant_labs_role(coordinator, "user")
        client.force_authenticate(user=coordinator)
        headers = _idempotency_headers()
        url = _approval_action(booking.pk, "reject")

        first = client.post(url, {"reason": "Needs details"}, format="json", **headers)
        mismatch = client.post(url, {"reason": "Different"}, format="json", **headers)

        assert first.status_code == 200
        assert mismatch.status_code == 422
        assert mismatch.json()["error"]["code"] == "idempotency_key_reuse"
        assert booking.decision_receipts.count() == 1

    def test_patch_rejects_in_progress_status(self, api_client, make_booking, future_window):
        starts_at, ends_at = future_window
        booking = make_booking(starts_at=starts_at, ends_at=ends_at)
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.patch(_detail(booking.pk), {"status": "in_progress"}, format="json")
        assert response.status_code in (400, 422)
