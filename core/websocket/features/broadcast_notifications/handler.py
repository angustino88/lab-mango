"""WS handler: broadcast notifications — ws/notifications/"""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from django.utils import timezone

from core.websocket import pubsub
from core.websocket.models import Notification
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL = "ws:notifications:broadcast"


@sync_to_async
def _get_active_broadcast_notifications() -> list[dict]:
    """Return all active unexpired broadcast notifications, ordered by creation."""
    qs = Notification.objects.filter(
        expiry_date__gt=timezone.now(),
        target_user__isnull=True,
    ).order_by("created")
    return [
        {
            "type": "notification",
            "id": n.pk,
            "message": n.message,
            "details": n.details or "",
            "message_type": n.message_type,
            "expiry_date": n.expiry_date.isoformat() if n.expiry_date else None,
            "created": n.created.isoformat(),
        }
        for n in qs
    ]


async def _send_initial_broadcast_notifications(send) -> None:
    try:
        notifications = await _get_active_broadcast_notifications()
        for payload in notifications:
            await send({"type": "websocket.send", "text": json.dumps(payload)})
    except Exception:
        logger.error("[WS] Error pushing initial broadcast notifications", exc_info=True)


async def broadcast_notifications_handler(scope: dict, receive, send) -> None:
    """Push all broadcast notifications to connected client."""
    await send({"type": "websocket.accept"})

    # Immediately push all active unexpired broadcast notifications on connection
    await _send_initial_broadcast_notifications(send)

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
