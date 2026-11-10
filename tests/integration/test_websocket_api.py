from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.websocket.models import Notification
from tests.factories import UserFactory


@pytest.mark.django_db
class TestListNotifications:
    def test_authenticated_user_only_sees_broadcast_and_own_targeted_notifications(self):
        current_user = UserFactory(username="notifyuser")
        other_user = UserFactory(username="othernotifyuser")

        broadcast = Notification.objects.create(
            message="broadcast",
            expiry_date=timezone.now() + timedelta(hours=1),
        )
        own_targeted = Notification.objects.create(
            message="own",
            expiry_date=timezone.now() + timedelta(hours=1),
            target_user=current_user,
        )
        Notification.objects.create(
            message="other",
            expiry_date=timezone.now() + timedelta(hours=1),
            target_user=other_user,
        )

        client = APIClient()
        client.force_authenticate(user=current_user)

        response = client.get("/api/notifications")

        assert response.status_code == 200
        data = response.json()["data"]
        returned_ids = {item["id"] for item in data}

        assert broadcast.id in returned_ids
        assert own_targeted.id in returned_ids
        assert len(returned_ids) == 2

    def test_user_id_filter_rejects_other_users(self):
        current_user = UserFactory(username="notifyguard")
        other_user = UserFactory(username="notifyguardother")

        client = APIClient()
        client.force_authenticate(user=current_user)

        response = client.get(f"/api/notifications?user_id={other_user.id}")

        assert response.status_code == 200
        assert response.json()["data"] == []


@pytest.mark.django_db
class TestCustomerNotificationDelivery:
    def test_notification_clean_rejects_past_expiry_date(self):
        from django.core.exceptions import ValidationError

        notif = Notification(
            message="Test message",
            expiry_date=timezone.now() - timedelta(minutes=10),
        )
        with pytest.raises(ValidationError, match="Expiry date must be in the future"):
            notif.clean()

    @pytest.mark.asyncio
    async def test_get_active_user_notifications_on_connect(self):
        from asgiref.sync import sync_to_async

        from core.websocket.features.user_notifications.handler import _get_active_user_notifications

        user_a = await sync_to_async(UserFactory)(username="user_a")
        user_b = await sync_to_async(UserFactory)(username="user_b")

        # Active broadcast
        bcast = await Notification.objects.acreate(
            message="Active broadcast",
            expiry_date=timezone.now() + timedelta(hours=2),
        )
        # Active targeted to user_a
        targeted_a = await Notification.objects.acreate(
            message="Targeted to A",
            expiry_date=timezone.now() + timedelta(hours=2),
            target_user=user_a,
        )
        # Targeted to user_b
        await Notification.objects.acreate(
            message="Targeted to B",
            expiry_date=timezone.now() + timedelta(hours=2),
            target_user=user_b,
        )
        # Expired broadcast
        await Notification.objects.acreate(
            message="Expired broadcast",
            expiry_date=timezone.now() - timedelta(hours=1),
        )

        active_notifs = await _get_active_user_notifications(user_a.id)
        active_ids = {item["id"] for item in active_notifs}

        assert active_ids == {bcast.id, targeted_a.id}
        for item in active_notifs:
            assert "expiry_date" in item
            assert item["expiry_date"] is not None

    @pytest.mark.asyncio
    async def test_get_active_broadcast_notifications_on_connect(self):
        from asgiref.sync import sync_to_async

        from core.websocket.features.broadcast_notifications.handler import _get_active_broadcast_notifications

        user = await sync_to_async(UserFactory)(username="user_c")

        # Active broadcast
        bcast = await Notification.objects.acreate(
            message="Active broadcast only",
            expiry_date=timezone.now() + timedelta(hours=2),
        )
        # Targeted (should NOT be in broadcast list)
        targeted = await Notification.objects.acreate(
            message="Targeted",
            expiry_date=timezone.now() + timedelta(hours=2),
            target_user=user,
        )
        # Expired
        await Notification.objects.acreate(
            message="Expired",
            expiry_date=timezone.now() - timedelta(hours=1),
        )

        broadcast_notifs = await _get_active_broadcast_notifications()
        broadcast_ids = {n["id"] for n in broadcast_notifs}
        assert bcast.id in broadcast_ids
        # Targeted notifications must never be in broadcast
        assert not any(n["id"] == targeted.id for n in broadcast_notifs)
