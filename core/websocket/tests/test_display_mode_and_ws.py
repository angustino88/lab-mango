"""Tests for display_mode DB constraint and canonical WebSocket replay payloads."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from core.websocket.features.broadcast_notifications.handler import _get_active_broadcast_notifications
from core.websocket.features.user_notifications.handler import _get_active_user_notifications
from core.websocket.models import Notification, NotificationRead
from core.websocket.publish_service import publish_notification_record

User = get_user_model()


@pytest.mark.django_db
def test_database_rejects_unknown_display_mode():
    with pytest.raises(IntegrityError):
        Notification.objects.create(
            message="Bad mode",
            display_mode="popup",
            expiry_date=timezone.now() + timedelta(hours=1),
        )


@pytest.mark.django_db(transaction=True)
def test_broadcast_and_user_ws_replays_include_replay_is_read_and_display_mode():
    user = User.objects.create_user(username="ws-replay-user")
    banner = Notification.objects.create(
        message="Lab maintenance",
        details="Offline at 18:00",
        message_type=Notification.WARNING,
        display_mode=Notification.BANNER,
        is_dismissible=False,
        expiry_date=timezone.now() + timedelta(hours=3),
    )
    alert = Notification.objects.create(
        message="One-time ping",
        message_type=Notification.INFO,
        display_mode=Notification.ALERT,
        expiry_date=timezone.now() + timedelta(hours=3),
    )
    NotificationRead.objects.create(user=user, notification=alert)

    broadcast_items = asyncio.run(_get_active_broadcast_notifications(user.pk))
    user_items = asyncio.run(_get_active_user_notifications(user.pk))

    for items in (broadcast_items, user_items):
        by_id = {row["id"]: row for row in items}
        assert set(by_id) == {banner.pk, alert.pk}
        assert by_id[banner.pk]["replay"] is True
        assert by_id[banner.pk]["display_mode"] == Notification.BANNER
        assert by_id[banner.pk]["is_dismissible"] is False
        assert by_id[banner.pk]["is_read"] is False
        assert by_id[alert.pk]["replay"] is True
        assert by_id[alert.pk]["display_mode"] == Notification.ALERT
        assert by_id[alert.pk]["is_read"] is True


@pytest.mark.django_db
def test_publish_notification_record_routes_strictly_to_target_or_broadcast():
    user = User.objects.create_user(username="ws-target-user")
    targeted = Notification.objects.create(
        message="Only for you",
        target_user=user,
        expiry_date=timezone.now() + timedelta(hours=1),
    )
    broadcast = Notification.objects.create(
        message="For everyone",
        display_mode=Notification.BANNER,
        expiry_date=timezone.now() + timedelta(hours=1),
    )

    with patch("core.websocket.publish_service._publish") as publish_mock:
        publish_notification_record(targeted, event="created")
        publish_notification_record(broadcast, event="created")

    assert publish_mock.call_count == 2
    first_channel, first_payload = publish_mock.call_args_list[0].args
    second_channel, second_payload = publish_mock.call_args_list[1].args
    assert first_channel == f"ws:notifications:user:{user.pk}"
    assert first_payload["display_mode"] == Notification.ALERT
    assert first_payload["replay"] is False
    assert second_channel == "ws:notifications:broadcast"
    assert second_payload["display_mode"] == Notification.BANNER
    assert second_payload["replay"] is False
