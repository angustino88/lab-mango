"""Unit tests for NotificationAdmin expiry_date date/time picker widget."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone

from core.websocket.models import Notification

User = get_user_model()


def _notification_admin_form_class():
    request = RequestFactory().get("/admin/websocket/notification/add/")
    request.user = User(username="admin", is_superuser=True, is_staff=True)
    model_admin = admin.site._registry[Notification]
    return model_admin.get_form(request)


def test_notification_admin_expiry_date_renders_date_and_time_pickers():
    form_class = _notification_admin_form_class()
    form = form_class()
    rendered = str(form["expiry_date"])

    assert 'type="date"' in rendered
    assert 'type="time"' in rendered
    assert 'name="expiry_date_0"' in rendered
    assert 'name="expiry_date_1"' in rendered


def test_notification_admin_expiry_date_parses_and_formats_iso_date_and_time():
    form_class = _notification_admin_form_class()
    future = (timezone.localtime(timezone.now()) + timedelta(days=2)).replace(second=0, microsecond=0)
    date_str = future.strftime("%Y-%m-%d")
    time_str = future.strftime("%H:%M")

    form = form_class(
        data={
            "message": "Scheduled maintenance",
            "details": "Lab A offline",
            "message_type": Notification.INFO,
            "expiry_date_0": date_str,
            "expiry_date_1": time_str,
        }
    )

    assert form.is_valid(), form.errors
    cleaned = form.cleaned_data["expiry_date"]
    assert timezone.is_aware(cleaned)
    local_cleaned = timezone.localtime(cleaned)
    assert local_cleaned.strftime("%Y-%m-%d %H:%M") == f"{date_str} {time_str}"

    # Existing instance renders ISO YYYY-MM-DD and HH:MM values compatible with HTML5 inputs.
    existing = Notification(
        message="Existing",
        message_type=Notification.INFO,
        expiry_date=datetime(2027, 3, 15, 14, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
    )
    edit_form = form_class(instance=existing)
    rendered_edit = str(edit_form["expiry_date"])
    assert 'value="2027-03-15"' in rendered_edit
    assert 'value="14:30"' in rendered_edit
