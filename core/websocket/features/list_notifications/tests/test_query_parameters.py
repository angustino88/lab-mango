"""since / user_id on GET /api/notifications behave as the OpenAPI contract documents."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from core.websocket.features.list_notifications.api import NotificationListCreateView
from core.websocket.models import Notification

ROOT = "/api/notifications"


@pytest.fixture
def caller(db):
    return get_user_model().objects.create_user(username="notification-caller")


@pytest.fixture
def other(db):
    return get_user_model().objects.create_user(username="notification-other")


@pytest.fixture
def client(caller):
    result = APIClient()
    result.force_authenticate(caller)
    return result


@pytest.fixture
def notifications(caller, other):
    future = timezone.now() + timedelta(days=1)
    broadcast = Notification.objects.create(message="broadcast", expiry_date=future)
    own = Notification.objects.create(message="own", expiry_date=future, target_user=caller)
    Notification.objects.create(message="other", expiry_date=future, target_user=other)
    expired = Notification.objects.create(message="expired", expiry_date=future, target_user=caller)
    Notification.objects.filter(pk=expired.pk).update(expiry_date=timezone.now() - timedelta(days=1))
    return broadcast, own


def _ids(response):
    assert response.status_code == 200, response.data
    return {row["id"] for row in response.data["data"]}


@pytest.mark.django_db
def test_without_filters_lists_visible_unexpired_notifications(client, notifications):
    broadcast, own = notifications
    assert _ids(client.get(ROOT)) == {broadcast.pk, own.pk}


@pytest.mark.django_db
def test_since_returns_only_newer_ids(client, notifications):
    broadcast, own = notifications
    assert _ids(client.get(ROOT, {"since": broadcast.pk})) == {own.pk}
    assert _ids(client.get(ROOT, {"since": own.pk})) == set()


@pytest.mark.django_db
def test_user_id_returns_only_own_targeted_notifications(client, caller, notifications):
    _broadcast, own = notifications
    assert _ids(client.get(ROOT, {"user_id": caller.pk})) == {own.pk}


@pytest.mark.django_db
def test_user_id_of_another_user_returns_an_empty_page(client, other, notifications):
    response = client.get(ROOT, {"user_id": other.pk})
    assert _ids(response) == set()
    assert response.data["meta"]["pagination"]["count"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("query", [{"since": "abc"}, {"since": "-1"}, {"user_id": "abc"}])
def test_values_that_are_not_non_negative_integers_are_ignored(client, notifications, query):
    broadcast, own = notifications
    assert _ids(client.get(ROOT, query)) == {broadcast.pk, own.pk}


def test_since_and_user_id_are_documented():
    document = SchemaGenerator(patterns=[path("notifications", NotificationListCreateView.as_view())]).get_schema(
        public=True
    )
    parameters = {item["name"]: item for item in document["paths"]["/notifications"]["get"]["parameters"]}
    for name in ("since", "user_id"):
        assert parameters[name]["in"] == "query"
        assert not parameters[name].get("required", False)
        assert parameters[name]["schema"] == {"type": "integer", "minimum": 0}
        assert parameters[name]["description"]
