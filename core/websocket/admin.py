"""Admin: Notification model with send-via-Redis action."""

import logging

from asgiref.sync import async_to_sync
from django.contrib import admin
from django.utils import timezone

from core.websocket import pubsub
from core.websocket.models import Notification

logger = logging.getLogger(__name__)


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
    actions = [send_notification_action]

    def save_model(self, request, obj, form, change) -> None:
        """Auto-publish to Redis when creating or saving an unexpired notification from admin."""
        super().save_model(request, obj, form, change)
        if obj.expiry_date and obj.expiry_date > timezone.now():
            _publish_notification(obj)
