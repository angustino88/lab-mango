"""Unit tests for bench booking rules that do not require database setup."""

from datetime import datetime, timedelta, timezone

import pytest
from django.core.exceptions import ValidationError

from core.labs.features.bench_bookings.application import policies
from core.labs.features.bench_bookings.application.booking_codes import generate_booking_code
from core.labs.models import BookingApprovalStatus


def test_start_grace_allows_exactly_ten_minutes_in_past():
    now = datetime(2026, 10, 16, 11, 40, tzinfo=timezone.utc)

    policies.ensure_startable(now - policies.START_GRACE, now=now)


def test_start_grace_rejects_more_than_ten_minutes_in_past():
    now = datetime(2026, 10, 16, 11, 40, tzinfo=timezone.utc)

    with pytest.raises(ValidationError) as error:
        policies.ensure_startable(now - policies.START_GRACE - timedelta(microseconds=1), now=now)
    assert error.value.message_dict["starts_at"] == [
        f"A booking cannot start more than {policies.format_duration(policies.START_GRACE)} in the past."
    ]


def test_minimum_duration_accepts_exactly_ten_minutes():
    starts_at = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)

    policies.ensure_minimum_duration(starts_at, starts_at + policies.MIN_BOOKING_DURATION)


def test_minimum_duration_rejects_less_than_ten_minutes():
    starts_at = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError) as error:
        policies.ensure_minimum_duration(
            starts_at, starts_at + policies.MIN_BOOKING_DURATION - timedelta(microseconds=1)
        )
    assert error.value.message_dict["ends_at"] == [
        f"Minimum booking duration is {policies.format_duration(policies.MIN_BOOKING_DURATION)}."
    ]


def test_four_hour_booking_is_approved():
    assert policies.default_approval_status(policies.LONG_BOOKING_APPROVAL_THRESHOLD) == BookingApprovalStatus.APPROVED


def test_booking_longer_than_four_hours_requires_approval():
    assert (
        policies.default_approval_status(policies.LONG_BOOKING_APPROVAL_THRESHOLD + timedelta(microseconds=1))
        == BookingApprovalStatus.PENDING
    )


def test_schedule_change_over_four_hours_requires_fresh_approval():
    assert (
        policies.approval_status_for_schedule_change(
            duration=policies.LONG_BOOKING_APPROVAL_THRESHOLD + timedelta(microseconds=1),
            current_status=BookingApprovalStatus.APPROVED,
        )
        == BookingApprovalStatus.PENDING
    )


def test_schedule_change_at_or_under_four_hours_preserves_current_approval():
    assert (
        policies.approval_status_for_schedule_change(
            duration=policies.LONG_BOOKING_APPROVAL_THRESHOLD,
            current_status=BookingApprovalStatus.APPROVED,
        )
        == BookingApprovalStatus.APPROVED
    )
    assert (
        policies.approval_status_for_schedule_change(
            duration=policies.LONG_BOOKING_APPROVAL_THRESHOLD,
            current_status=BookingApprovalStatus.PENDING,
        )
        == BookingApprovalStatus.PENDING
    )


def test_hash_derived_booking_codes_are_unique_per_generation():
    starts_at = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)
    ends_at = starts_at + timedelta(hours=1)

    first_code = generate_booking_code(bench_id=1, starts_at=starts_at, ends_at=ends_at)
    second_code = generate_booking_code(bench_id=1, starts_at=starts_at, ends_at=ends_at)

    assert first_code.startswith("BOOKING-")
    assert len(first_code) == len("BOOKING-") + 14
    assert first_code != second_code
