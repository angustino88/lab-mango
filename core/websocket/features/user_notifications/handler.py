"""WS handler: per-user notifications — ws/user/"""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from django.db.models import Q
from django.utils import timezone

from core.websocket import pubsub
from core.websocket.models import Notification
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

BROADCAST_CHANNEL = "ws:notifications:broadcast"
USER_CHANNEL_PREFIX = "ws:notifications:user:"


@sync_to_async
def _get_active_user_notifications(user_id: int) -> list[dict]:
    """Return up to 50 unexpired notifications applicable to this user, ordered by creation."""
    qs = (
        Notification.objects.filter(expiry_date__gt=timezone.now())
        .filter(Q(target_user__isnull=True) | Q(target_user_id=user_id))
        .order_by("-created")[:50]
    )

    # Reverse the queryset to replay oldest first from the bounded set
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
        for n in reversed(list(qs))
    ]


async def _send_initial_notifications(send, user_id: int) -> None:
    try:
        notifications = await _get_active_user_notifications(user_id)
        for payload in notifications:
            await send({"type": "websocket.send", "text": json.dumps(payload)})
    except Exception:
        logger.error(f"[WS] Error pushing initial notifications for user {user_id}", exc_info=True)


async def user_notifications_handler(scope: dict, receive, send) -> None:
    """Push broadcast + user-specific notifications to authenticated user."""
    user_id = scope.get("user_id")
    if not user_id:
        await send({"type": "websocket.close", "code": 4001})
        return

    await send({"type": "websocket.accept"})

    # Immediately push active unexpired notifications on connection
    await _send_initial_notifications(send, user_id)

    user_channel = f"{USER_CHANNEL_PREFIX}{user_id}"

    # Listen to both broadcast and user-specific channels concurrently
    broadcast_task = asyncio.create_task(_listen_redis(send, BROADCAST_CHANNEL))
    user_task = asyncio.create_task(_listen_redis(send, user_channel))

    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
    except Exception:
        logger.debug("User WS disconnected (user=%s)", user_id, exc_info=True)
    finally:
        broadcast_task.cancel()
        user_task.cancel()
        for task in (broadcast_task, user_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _listen_redis(send, channel: str) -> None:
    """Subscribe to Redis channel and forward to WS client."""
    try:
        async for data in pubsub.subscribe(channel):
            await send({"type": "websocket.send", "text": json.dumps(data)})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("Redis subscription error (%s)", channel, exc_info=True)


register_route("ws/user", user_notifications_handler)
