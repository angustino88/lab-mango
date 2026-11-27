"""Service: create notification and publish to Redis."""

import logging
from datetime import datetime

from asgiref.sync import sync_to_async
from django.utils import timezone

from core.websocket import pubsub
from core.websocket.models import Notification
from core.websocket.publish_service import serialize_notification_payload

logger = logging.getLogger(__name__)

BROADCAST_CHANNEL = "ws:notifications:broadcast"
USER_CHANNEL_PREFIX = "ws:notifications:user:"


async def create_and_publish(
    message: str,
    message_type: str = Notification.INFO,
    details: str = "",
    expiry_date: datetime | None = None,
    target_user_id: int | None = None,
    *,
    display_mode: str = Notification.ALERT,
    is_dismissible: bool = True,
) -> Notification:
    """Create notification in DB, then publish to Redis pub/sub."""
    now = timezone.now()
    notification = await sync_to_async(Notification.objects.create)(
        message=message,
        details=details,
        message_type=message_type,
        display_mode=display_mode,
        is_dismissible=is_dismissible,
        published_at=now,
        expiry_date=expiry_date,
        target_user_id=target_user_id,
    )

    payload = serialize_notification_payload(notification, event="created", is_read=False, replay=False)

    if target_user_id:
        await pubsub.publish(f"{USER_CHANNEL_PREFIX}{target_user_id}", payload)
    else:
        await pubsub.publish(BROADCAST_CHANNEL, payload)

    return notification
