"""Fixtures for bench booking feature tests."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.labs.models import Bench, BenchBooking, BookingStatus, EquipmentAssignment
from core.labs.models.booking.reference_data import LabProject
from core.users.tests.factories import UserFactory


@pytest.fixture()
def actor(db):
    """A plain Labs user: bench bookings are open to every Labs role."""
    from tests.factories import grant_labs_role

    return grant_labs_role(UserFactory(username="bench-booking-actor"), "member")


def place_computer(bench, *, sku):
    """Put a computer on the bench: a bench without one cannot be booked."""
    from tests.factories import create_computing_equipment

    EquipmentAssignment.objects.create(
        bench=bench,
        equipment=create_computing_equipment(sku=sku, name=f"{sku}-NAME"),
        position=0,
        assigned_at=timezone.now() - timedelta(hours=1),
    )
    return bench


@pytest.fixture()
def bench(db):
    return place_computer(Bench.objects.create(sku="BB-BENCH-01", name="Bench 01"), sku="BB-PC-01")


@pytest.fixture()
def other_bench(db):
    return place_computer(Bench.objects.create(sku="BB-BENCH-02", name="Bench 02"), sku="BB-PC-02")


@pytest.fixture()
def project(db):
    return LabProject.objects.create(project_name="Test Project")


@pytest.fixture()
def now():
    return timezone.now()


@pytest.fixture()
def make_booking(db, bench, actor):
    def _make(*, starts_at, ends_at, bench_obj=None, status=BookingStatus.RESERVED, code=None):
        booking = BenchBooking(
            bench=bench_obj or bench,
            starts_at=starts_at,
            ends_at=ends_at,
            status=status,
            booking_code=code or f"BOOKING-TEST-{BenchBooking.objects.count() + 1:04d}",
            # The database requires a reason on cancelled bookings (Booking.clean() invariant).
            cancellation_reason="Cancelled in test setup" if status == BookingStatus.CANCELLED else "",
            # The database requires a completion time exactly on completed bookings.
            completed_at=ends_at if status == BookingStatus.COMPLETED else None,
        )
        booking.save(actor=actor)
        return booking

    return _make


@pytest.fixture()
def api_client(db, actor):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=actor)
    return client


@pytest.fixture()
def future_window(now):
    return now + timedelta(hours=2), now + timedelta(hours=3)
