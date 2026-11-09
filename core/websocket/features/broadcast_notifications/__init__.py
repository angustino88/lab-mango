"""Service: create notification and publish to Redis."""

import logging
from datetime import datetime

from asgiref.sync import sync_to_async

from core.websocket import pubsub
from core.websocket.models import Notification

logger = logging.getLogger(__name__)

BROADCAST_CHANNEL = "ws:notifications:broadcast"
USER_CHANNEL_PREFIX = "ws:notifications:user:"


async def create_and_publish(
    message: str,
    message_type: str = Notification.INFO,
    details: str = "",
    expiry_date: datetime | None = None,
    target_user_id: int | None = None,
) -> Notification:
    """Create notification in DB, then publish to Redis pub/sub."""
    notification = await sync_to_async(Notification.objects.create)(
        message=message,
        details=details,
        message_type=message_type,
        expiry_date=expiry_date,
        target_user_id=target_user_id,
    )

    payload = _serialize(notification)

    # Always publish to broadcast channel
    await pubsub.publish(BROADCAST_CHANNEL, payload)

    # Also publish to user-specific channel if targeted
    if target_user_id:
        await pubsub.publish(f"{USER_CHANNEL_PREFIX}{target_user_id}", payload)

    return notification


def _serialize(n: Notification) -> dict:
    return {
        "type": "notification",
        "id": n.pk,
        "message": n.message,
        "details": n.details or "",
        "message_type": n.message_type,
        "created": n.created.isoformat(),
    }
