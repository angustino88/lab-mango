"""Tests for BannerNotificationAdmin and AlertNotificationAdmin workflows."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.utils import timezone

from core.websocket.admin import expire_banners_now
from core.websocket.models import AlertNotification, BannerNotification, Notification

User = get_user_model()


def _admin_request(path: str):
    request = RequestFactory().get(path)
    request.user = User(username="admin", is_superuser=True, is_staff=True)
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_banner_admin_expiry_date_renders_date_and_time_pickers():
    request = _admin_request("/admin/websocket/bannernotification/add/")
    model_admin = admin.site._registry[BannerNotification]
    form_class = model_admin.get_form(request)
    form = form_class()
    rendered = str(form["expiry_date"])

    assert 'type="date"' in rendered
    assert 'type="time"' in rendered
    assert 'name="expiry_date_0"' in rendered
    assert 'name="expiry_date_1"' in rendered
    assert 'data-preset="hours:1"' in rendered
    assert 'data-preset="tomorrow:18:00"' in rendered
    assert 'data-timezone="Asia/Ho_Chi_Minh"' in rendered
    assert 'data-preset="clear"' not in rendered
    media_html = str(form.media)
    assert "websocket/admin_datetime_picker.css" in media_html
    assert "websocket/admin_datetime_picker.js" in media_html


def test_alert_admin_expiry_date_includes_clear_button():
    request = _admin_request("/admin/websocket/alertnotification/add/")
    model_admin = admin.site._registry[AlertNotification]
    form_class = model_admin.get_form(request)
    rendered = str(form_class()["expiry_date"])
    assert 'data-preset="clear"' in rendered
    assert 'data-allow-clear="true"' in rendered


def test_banner_admin_expiry_date_parses_and_formats_iso_date_and_time():
    request = _admin_request("/admin/websocket/bannernotification/add/")
    model_admin = admin.site._registry[BannerNotification]
    form_class = model_admin.get_form(request)
    future = (timezone.localtime(timezone.now()) + timedelta(days=2)).replace(second=0, microsecond=0)
    date_str = future.strftime("%Y-%m-%d")
    time_str = future.strftime("%H:%M")

    form = form_class(
        data={
            "message": "Scheduled maintenance",
            "details": "Lab A offline",
            "message_type": Notification.WARNING,
            "expiry_date_0": date_str,
            "expiry_date_1": time_str,
            "is_dismissible": True,
        }
    )

    assert form.is_valid(), form.errors
    cleaned = form.cleaned_data["expiry_date"]
    assert timezone.is_aware(cleaned)
    local_cleaned = timezone.localtime(cleaned)
    assert local_cleaned.strftime("%Y-%m-%d %H:%M") == f"{date_str} {time_str}"

    # Existing instance renders ISO YYYY-MM-DD and HH:MM values compatible with HTML5 inputs.
    existing = BannerNotification(
        message="Existing",
        message_type=Notification.INFO,
        display_mode=Notification.BANNER,
        expiry_date=datetime(2027, 3, 15, 14, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
    )
    edit_form = form_class(instance=existing)
    rendered_edit = str(edit_form["expiry_date"])
    assert 'value="2027-03-15"' in rendered_edit
    assert 'value="14:30"' in rendered_edit


def test_alert_admin_form_defaults_expiry_date_when_omitted():
    request = _admin_request("/admin/websocket/alertnotification/add/")
    model_admin = admin.site._registry[AlertNotification]
    form_class = model_admin.get_form(request)

    form = form_class(
        data={
            "message": "Lab A power restored",
            "details": "All benches back online",
            "message_type": Notification.SUCCESS,
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["expiry_date"] > timezone.now() + timedelta(days=6)


@pytest.mark.django_db
def test_alert_admin_publishes_strictly_once_and_never_on_edit(django_capture_on_commit_callbacks):
    request = _admin_request("/admin/websocket/alertnotification/add/")
    model_admin = admin.site._registry[AlertNotification]
    obj = AlertNotification(
        message="Quick heads-up",
        details="Check bench cables",
        message_type=Notification.INFO,
        expiry_date=timezone.now() + timedelta(days=1),
    )

    with (
        patch("core.websocket.admin.publish_notification_record") as publish_mock,
        django_capture_on_commit_callbacks(execute=True),
    ):
        model_admin.save_model(request, obj, form=None, change=False)

    assert obj.display_mode == Notification.ALERT
    assert obj.is_dismissible is True
    assert obj.published_at is not None
    publish_mock.assert_called_once_with(obj, event="created")

    # Editing the existing alert must NEVER re-broadcast a popup.
    obj.message = "Quick heads-up (typo fixed)"
    with (
        patch("core.websocket.admin.publish_notification_record") as publish_mock,
        django_capture_on_commit_callbacks(execute=True),
    ):
        model_admin.save_model(request, obj, form=None, change=True)

    publish_mock.assert_not_called()


@pytest.mark.django_db
def test_banner_admin_publishes_upsert_and_removal_events(django_capture_on_commit_callbacks):
    request = _admin_request("/admin/websocket/bannernotification/add/")
    model_admin = admin.site._registry[BannerNotification]
    obj = BannerNotification(
        message="Planned maintenance",
        details="Saturday 09:00-12:00",
        message_type=Notification.WARNING,
        expiry_date=timezone.now() + timedelta(hours=6),
        is_dismissible=False,
    )

    with (
        patch("core.websocket.admin.publish_notification_record") as publish_mock,
        django_capture_on_commit_callbacks(execute=True),
    ):
        model_admin.save_model(request, obj, form=None, change=False)

    assert obj.display_mode == Notification.BANNER
    assert obj.is_dismissible is False
    publish_mock.assert_called_once_with(obj, event="created")

    # Editing an active banner sends an in-place update event.
    obj.details = "Saturday 09:00-13:00"
    with (
        patch("core.websocket.admin.publish_notification_record") as publish_mock,
        django_capture_on_commit_callbacks(execute=True),
    ):
        model_admin.save_model(request, obj, form=None, change=True)

    publish_mock.assert_called_once_with(obj, event="updated")

    # Expiring via bulk action sets expiry_date <= now and broadcasts removal.
    with (
        patch("core.websocket.admin.publish_notification_removed") as remove_mock,
        django_capture_on_commit_callbacks(execute=True),
    ):
        expire_banners_now(model_admin, request, BannerNotification.objects.filter(pk=obj.pk))

    obj.refresh_from_db()
    assert obj.expiry_date <= timezone.now()
    remove_mock.assert_called_once_with(obj.pk, display_mode=Notification.BANNER, target_user_id=None)
