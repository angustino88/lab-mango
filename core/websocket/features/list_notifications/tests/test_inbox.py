"""Header bell inbox: per-user read state, unread count, mark read / mark all read."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from core.websocket.models import Notification, NotificationRead

URL = "/api/notifications"


def _notify(user=None, **extra):
    message = extra.pop("message", "Bench 07 frees up at 14:00")
    return Notification.objects.create(
        message=message,
        expiry_date=timezone.now() + timedelta(hours=1),
        target_user=user,
        **extra,
    )


@pytest.fixture()
def me(db):
    return UserFactory(username="bell-me")


@pytest.fixture()
def client(me):
    api = APIClient()
    api.force_authenticate(me)
    return api


@pytest.mark.django_db
class TestInbox:
    def test_unread_count_mark_read_and_filters(self, client, me):
        mine = _notify(me, action_path="/booking-calendar?action=create")
        broadcast = _notify(None)
        _notify(UserFactory(username="bell-other"))  # someone else's: invisible

        assert client.get(f"{URL}/unread-count").json()["data"]["unread_count"] == 2
        listed = client.get(URL).json()["data"]
        assert {row["id"]: row["is_read"] for row in listed} == {mine.pk: False, broadcast.pk: False}

        response = client.post(f"{URL}/{mine.pk}/actions/mark-read")
        assert response.status_code == 200 and response.json()["data"]["is_read"] is True
        assert client.post(f"{URL}/{mine.pk}/actions/mark-read").status_code == 200  # idempotent
        assert NotificationRead.objects.filter(user=me).count() == 1

        assert client.get(f"{URL}/unread-count").json()["data"]["unread_count"] == 1
        assert [row["id"] for row in client.get(URL, {"unread": "true"}).json()["data"]] == [broadcast.pk]
        assert [row["id"] for row in client.get(URL, {"unread": "false"}).json()["data"]] == [mine.pk]

    def test_mark_all_read(self, client, me):
        _notify(me)
        _notify(None)
        assert client.post(f"{URL}/actions/mark-all-read").json()["data"]["marked_count"] == 2
        assert client.post(f"{URL}/actions/mark-all-read").json()["data"]["marked_count"] == 0
        assert client.get(f"{URL}/unread-count").json()["data"]["unread_count"] == 0

    def test_broadcast_read_state_is_per_user(self, client, me):
        broadcast = _notify(None)
        client.post(f"{URL}/{broadcast.pk}/actions/mark-read")
        other = APIClient()
        other.force_authenticate(UserFactory(username="bell-colleague"))
        assert other.get(f"{URL}/unread-count").json()["data"]["unread_count"] == 1

    def test_cannot_mark_someone_elses_notification(self, client):
        theirs = _notify(UserFactory(username="bell-owner"))
        assert client.post(f"{URL}/{theirs.pk}/actions/mark-read").status_code == 404
        assert not NotificationRead.objects.exists()

    def test_invalid_unread_value(self, client):
        assert client.get(URL, {"unread": "yes"}).status_code == 400

    def test_invalid_display_mode_value(self, client):
        assert client.get(URL, {"display_mode": "popup"}).status_code == 400

    def test_banners_appear_in_all_history_without_counting_toward_unread_badge(self, client, me):
        alert = _notify(me, display_mode=Notification.ALERT)
        banner = _notify(
            None,
            message="Scheduled maintenance",
            message_type=Notification.WARNING,
            display_mode=Notification.BANNER,
            is_dismissible=True,
        )

        # Unread bell badge counts one-time alerts only, never banners.
        assert client.get(f"{URL}/unread-count").json()["data"]["unread_count"] == 1

        # Default "All" list includes both alerts and banners so users can re-read banners.
        all_rows = client.get(URL).json()["data"]
        by_id = {row["id"]: row for row in all_rows}
        assert set(by_id) == {alert.pk, banner.pk}
        assert by_id[banner.pk]["display_mode"]["value"] == Notification.BANNER
        assert by_id[banner.pk]["is_dismissible"] is True
        assert by_id[alert.pk]["display_mode"]["value"] == Notification.ALERT

        # display_mode filter separates banners from alerts cleanly.
        assert [row["id"] for row in client.get(URL, {"display_mode": "banner"}).json()["data"]] == [banner.pk]
        assert [row["id"] for row in client.get(URL, {"display_mode": "alert"}).json()["data"]] == [alert.pk]

        # Mark-all-read clears unread alerts without dismissing active banners.
        assert client.post(f"{URL}/actions/mark-all-read").json()["data"]["marked_count"] == 1
        assert client.get(f"{URL}/unread-count").json()["data"]["unread_count"] == 0
        banner_row = client.get(URL, {"display_mode": "banner"}).json()["data"][0]
        assert banner_row["is_read"] is False

        # Dismissing a banner explicitly records a per-user NotificationRead.
        dismissed = client.post(f"{URL}/{banner.pk}/actions/mark-read")
        assert dismissed.status_code == 200 and dismissed.json()["data"]["is_read"] is True

    def test_anonymous_is_rejected(self):
        assert APIClient().get(f"{URL}/unread-count").status_code in (401, 403)
