"""Admin: Notification model with send-via-Redis action."""

import logging

from asgiref.sync import async_to_sync
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminSplitDateTime, BaseAdminDateWidget, BaseAdminTimeWidget
from django.utils import timezone

from core.websocket import pubsub
from core.websocket.models import Notification

logger = logging.getLogger(__name__)


class _DateTimePickerWidget(AdminSplitDateTime):
    """SplitDateTime widget with native browser date and time selectors."""

    _INPUT_STYLE = (
        "border: 1px solid var(--border-color); border-radius: 4px; "
        "padding: 5px 6px; background: var(--body-bg); color: var(--body-fg);"
    )

    def __init__(self, attrs=None):
        widgets = [
            BaseAdminDateWidget(attrs={"type": "date", "style": self._INPUT_STYLE}, format="%Y-%m-%d"),
            BaseAdminTimeWidget(attrs={"type": "time", "style": self._INPUT_STYLE}, format="%H:%M"),
        ]
        forms.MultiWidget.__init__(self, widgets, attrs)


def _publish_notification(notification: Notification) -> None:
    payload = {
        "type": "notification",
        "id": notification.pk,
        "message": notification.message,
        "details": notification.details or "",
        "message_type": notification.message_type,
        "expiry_date": notification.expiry_date.isoformat() if notification.expiry_date else None,
        "created": notification.created.isoformat(),
    }

    if notification.target_user_id:
        try:
            async_to_sync(pubsub.publish)(
                f"ws:notifications:user:{notification.target_user_id}", payload
            )
            logger.info(
                f"[NOTIFY] Published user notification {notification.pk} to user {notification.target_user_id}"
            )
        except Exception as e:
            logger.error(f"[NOTIFY] Failed to publish user notification: {e}", exc_info=True)
    else:
        try:
            count = async_to_sync(pubsub.publish)("ws:notifications:broadcast", payload)
            logger.info(f"[NOTIFY] Published broadcast notification {notification.pk} — subscribers: {count}")
        except Exception as e:
            logger.error(f"[NOTIFY] Failed to publish notification {notification.pk}: {e}", exc_info=True)


def send_notification_action(modeladmin, request, queryset) -> None:
    """Admin action: publish selected notifications to WebSocket channels."""
    for notification in queryset:
        if notification.expiry_date and notification.expiry_date > timezone.now():
            _publish_notification(notification)


send_notification_action.short_description = "Send via WebSocket"  # type: ignore[attr-defined]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("message", "message_type", "expiry_date", "target_user", "created")
    list_filter = ("message_type",)
    search_fields = ("message", "details", "target_user__username", "target_user__email")
    autocomplete_fields = ("target_user",)
    # Action links are set by features (e.g. slot alerts' "Book now"), not typed by admins.
    exclude = ("action_path",)
    actions = [send_notification_action]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "expiry_date":
            kwargs["widget"] = _DateTimePickerWidget
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change) -> None:
        """Auto-publish to Redis when creating or saving an unexpired notification from admin."""
        super().save_model(request, obj, form, change)
        if obj.expiry_date and obj.expiry_date > timezone.now():
            _publish_notification(obj)
