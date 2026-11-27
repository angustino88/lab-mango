"""Header bell inbox: per-user read state, unread count, mark read / mark all read."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from core.websocket.models import Notification, NotificationRead

URL = "/api/notifications"


def _notify(user=None, **extra):
    return Notification.objects.create(
        message="Bench 07 frees up at 14:00",
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

    def test_anonymous_is_rejected(self):
        assert APIClient().get(f"{URL}/unread-count").status_code in (401, 403)
