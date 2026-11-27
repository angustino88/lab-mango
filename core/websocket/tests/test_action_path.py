"""Web notifications may carry an in-app action link; the database refuses external URLs."""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from core.websocket.models import Notification


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["https://evil.example/x", "//evil.example/x", "javascript:alert(1)"])
def test_external_action_links_are_refused(path):
    with pytest.raises(IntegrityError):
        Notification.objects.create(message="m", expiry_date=timezone.now() + timedelta(hours=1), action_path=path)


@pytest.mark.django_db
def test_in_app_action_link_is_kept():
    notification = Notification.objects.create(
        message="m", expiry_date=timezone.now() + timedelta(hours=1), action_path="/booking-calendar?action=create"
    )
    assert notification.action_path == "/booking-calendar?action=create"
