"""Ownership rule for bench booking edits: owner, lab coordinator, or lab admin only."""

import itertools
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.labs.features.bench_bookings.application import UpdateBenchBookingInput, update_bench_booking
from core.labs.features.bench_bookings.exceptions import BenchBookingPermissionDenied
from core.labs.models import BenchBooking, BookingStatus
from core.users.models import URSGroup
from core.users.tests.factories import UserFactory

_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"
_URS_IDS = itertools.count(70000)


def _user_with_role(username: str, role: str):
    group, _ = Group.objects.get_or_create(name=f"bb-own-{role}-{username}")
    URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role=role)
    user = UserFactory(username=username)
    user.groups.add(group)
    return user


@pytest.fixture()
def other_user(db):
    return _user_with_role("bb-other-user", "user")


@pytest.fixture()
def coordinator(db):
    return _user_with_role("bb-coordinator", "coord")


@pytest.fixture()
def lab_admin(db):
    return _user_with_role("bb-lab-admin", "admin")


@pytest.fixture()
def reserved_booking(actor, make_booking, now):
    return make_booking(starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))


@pytest.mark.django_db
class TestBookingEditOwnership:
    def test_owner_can_edit(self, actor, reserved_booking):
        updated = update_bench_booking(
            actor=actor,
            data=UpdateBenchBookingInput(booking_id=reserved_booking.pk, fields={"reason": "Owner edit"}),
        )
        assert updated.reason == "Owner edit"

    def test_coordinator_can_edit_others_booking(self, coordinator, reserved_booking):
        updated = update_bench_booking(
            actor=coordinator,
            data=UpdateBenchBookingInput(booking_id=reserved_booking.pk, fields={"reason": "Coord edit"}),
        )
        assert updated.reason == "Coord edit"

    def test_lab_admin_can_edit_others_booking(self, lab_admin, reserved_booking):
        updated = update_bench_booking(
            actor=lab_admin,
            data=UpdateBenchBookingInput(booking_id=reserved_booking.pk, fields={"reason": "Admin edit"}),
        )
        assert updated.reason == "Admin edit"

    def test_other_user_cannot_edit(self, other_user, reserved_booking):
        with pytest.raises(BenchBookingPermissionDenied):
            update_bench_booking(
                actor=other_user,
                data=UpdateBenchBookingInput(booking_id=reserved_booking.pk, fields={"reason": "Hijack"}),
            )
        assert BenchBooking.objects.get(pk=reserved_booking.pk).reason != "Hijack"

    def test_other_user_cannot_cancel(self, other_user, reserved_booking):
        with pytest.raises(BenchBookingPermissionDenied):
            update_bench_booking(
                actor=other_user,
                data=UpdateBenchBookingInput(
                    booking_id=reserved_booking.pk,
                    fields={"status": BookingStatus.CANCELLED},
                ),
            )
        assert BenchBooking.objects.get(pk=reserved_booking.pk).status == BookingStatus.RESERVED

    def test_other_user_cannot_complete(self, other_user, reserved_booking):
        with pytest.raises(BenchBookingPermissionDenied):
            update_bench_booking(
                actor=other_user,
                data=UpdateBenchBookingInput(
                    booking_id=reserved_booking.pk,
                    fields={"status": BookingStatus.COMPLETED},
                ),
            )
        assert BenchBooking.objects.get(pk=reserved_booking.pk).status == BookingStatus.RESERVED


@pytest.mark.django_db
class TestBookingEditOwnershipApi:
    def test_other_user_gets_403_envelope(self, other_user, reserved_booking):
        client = APIClient()
        client.force_authenticate(user=other_user)
        with patch(_PATCH_APIKEY, return_value=True):
            response = client.patch(
                f"/api/labs/bench-bookings/{reserved_booking.pk}",
                {"reason": "Hijack"},
                format="json",
            )
        assert response.status_code == 403
        assert BenchBooking.objects.get(pk=reserved_booking.pk).reason != "Hijack"

    def test_coordinator_can_cancel_others_booking(self, coordinator, reserved_booking):
        client = APIClient()
        client.force_authenticate(user=coordinator)
        with patch(_PATCH_APIKEY, return_value=True):
            response = client.post(
                f"/api/labs/bench-bookings/{reserved_booking.pk}/actions/cancel",
                {"reason": "Coordinator cancel"},
                format="json",
            )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == {"value": "cancelled", "label": "Cancelled"}
