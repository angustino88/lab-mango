"""WS handler: broadcast notifications — ws/notifications/"""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from django.db.models import Exists, OuterRef, Value
from django.utils import timezone

from core.websocket import pubsub
from core.websocket.models import Notification, NotificationRead
from core.websocket.publish_service import serialize_notification_payload
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL = "ws:notifications:broadcast"


@sync_to_async
def _get_active_broadcast_notifications(user_id: int | None = None) -> list[dict]:
    """Return up to 50 active unexpired broadcast notifications, ordered oldest first."""
    qs = Notification.objects.filter(
        expiry_date__gt=timezone.now(),
        target_user__isnull=True,
    )
    if user_id is not None:
        qs = qs.annotate(is_read=Exists(NotificationRead.objects.filter(user_id=user_id, notification=OuterRef("pk"))))
    else:
        qs = qs.annotate(is_read=Value(False))
    qs = qs.order_by("-created")[:50]
    return [
        serialize_notification_payload(n, is_read=bool(getattr(n, "is_read", False)), replay=True)
        for n in reversed(list(qs))
    ]


async def _send_initial_broadcast_notifications(send, user_id: int | None = None) -> None:
    try:
        notifications = await _get_active_broadcast_notifications(user_id)
        for payload in notifications:
            await send({"type": "websocket.send", "text": json.dumps(payload)})
    except Exception:
        logger.error("[WS] Error pushing initial broadcast notifications", exc_info=True)


async def broadcast_notifications_handler(scope: dict, receive, send) -> None:
    """Push all broadcast notifications to connected client."""
    await send({"type": "websocket.accept"})

    # Immediately push active unexpired broadcast notifications on connection (marked replay=True)
    await _send_initial_broadcast_notifications(send, scope.get("user_id"))

    listen_task = asyncio.create_task(_listen_redis(send))
    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
    except Exception:
        logger.debug("Broadcast WS disconnected", exc_info=True)
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass


async def _listen_redis(send) -> None:
    """Subscribe to Redis and forward messages to WS client."""
    try:
        async for data in pubsub.subscribe(CHANNEL):
            await send({"type": "websocket.send", "text": json.dumps(data)})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("Redis subscription error (broadcast)", exc_info=True)


register_route("ws/notifications", broadcast_notifications_handler)
