"""Unit tests for the shared booking lifecycle transition graph."""

import pytest
from django.core.exceptions import ValidationError

from core.labs.models import BookingStatus, ensure_booking_status_transition


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        (BookingStatus.RESERVED, BookingStatus.IN_PROGRESS),
        (BookingStatus.RESERVED, BookingStatus.CANCELLED),
        (BookingStatus.RESERVED, BookingStatus.EXPIRED),
        (BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED),
        (BookingStatus.IN_PROGRESS, BookingStatus.CANCELLED),
    ],
)
def test_allowed_booking_status_transition(current_status, target_status):
    ensure_booking_status_transition(current_status=current_status, target_status=target_status)


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        (BookingStatus.IN_PROGRESS, BookingStatus.RESERVED),
        (BookingStatus.IN_PROGRESS, BookingStatus.EXPIRED),
        (BookingStatus.COMPLETED, BookingStatus.RESERVED),
        (BookingStatus.CANCELLED, BookingStatus.RESERVED),
        (BookingStatus.EXPIRED, BookingStatus.RESERVED),
        (BookingStatus.EXPIRED, BookingStatus.IN_PROGRESS),
    ],
)
def test_invalid_booking_status_transition_is_rejected(current_status, target_status):
    with pytest.raises(ValidationError, match="Cannot transition booking"):
        ensure_booking_status_transition(current_status=current_status, target_status=target_status)


def test_same_status_transition_is_idempotent():
    ensure_booking_status_transition(
        current_status=BookingStatus.COMPLETED,
        target_status=BookingStatus.COMPLETED,
    )
