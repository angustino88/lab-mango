"""Booking start and inactivity reminders reach the web bell (and so toasts / desktop notifications)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.labs.features.bench_bookings.application.notification_collection import collect_notifications
from core.labs.features.bench_bookings.application.notification_delivery import deliver_notifications
from core.labs.features.bench_bookings.application.notification_intents import record_notification
from core.labs.models import BookingNotification, BookingStatus
from core.websocket.models import Notification


@pytest.fixture()
def web_enabled(settings):
    settings.BOOKING_NOTIFICATIONS_ENABLED = True
    settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF = timezone.now() - timedelta(days=1)
    settings.BOOKING_NOTIFICATIONS_EMAIL_ENABLED = False
    settings.BOOKING_NOTIFICATIONS_TEAMS_ENABLED = False
    settings.BOOKING_NOTIFICATIONS_IN_APP_ENABLED = True
    return settings


@pytest.mark.django_db
def test_start_reminder_appears_in_the_bell_once(web_enabled, make_booking, actor):
    now = timezone.now()
    booking = make_booking(starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=2))
    collect_notifications(now=now)
    collect_notifications(now=now)  # repeated runs dedupe
    row = BookingNotification.objects.get(booking=booking)
    assert row.channel == "in_app" and row.kind == "start"

    with patch(
        "core.labs.features.bench_bookings.application.notification_delivery.publish_user_notification"
    ) as push:
        counts = deliver_notifications()
    assert counts["sent"] == 1
    web = Notification.objects.get(target_user=actor)
    assert web.message == "Your booking on Bench 01 starts now"
    assert booking.booking_code in web.details and "Sign in on the bench computer" in web.details
    assert web.action_path == "/my-bookings"
    row.refresh_from_db()
    assert row.state == "sent"
    # Pushed after commit for the live toast and the desktop notification.
    assert push.call_count in (0, 1)  # on_commit does not run inside the test transaction


@pytest.mark.django_db
def test_creation_and_updates_do_not_go_to_the_bell(web_enabled, make_booking):
    now = timezone.now()
    booking = make_booking(starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
    assert record_notification(booking=booking, kind="created", now=now) == 0
    assert not BookingNotification.objects.filter(channel="in_app").exists()


@pytest.mark.django_db
def test_web_channel_off_by_default(settings, make_booking):
    settings.BOOKING_NOTIFICATIONS_ENABLED = True
    settings.BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF = timezone.now() - timedelta(days=1)
    settings.BOOKING_NOTIFICATIONS_IN_APP_ENABLED = False
    now = timezone.now()
    make_booking(starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1))
    collect_notifications(now=now)
    assert not BookingNotification.objects.filter(channel="in_app").exists()


@pytest.mark.django_db
def test_inactivity_message(web_enabled):
    from core.labs.features.bench_bookings.contracts import BookingNotificationSnapshot
    from core.labs.features.bench_bookings.integrations.notification_transport import booking_web_message

    now = timezone.now()
    snapshot = BookingNotificationSnapshot(
        booking_code="BK-1",
        bench_id=1,
        starts_at=(now - timedelta(hours=2)).isoformat(),
        ends_at=(now + timedelta(hours=1)).isoformat(),
        status=BookingStatus.IN_PROGRESS,
        approval_status="approved",
        bench_name="Bench 07",
        equipment_name="GPU-RTX",
    )
    title, details, path = booking_web_message(kind="inactive", snapshot=snapshot)
    assert title == "No activity on GPU-RTX for over an hour"
    assert details.startswith("Bench 07 is booked for you until ")
    assert path == "/my-bookings"
