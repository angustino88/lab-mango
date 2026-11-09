"""WS handler: per-user notifications — ws/user/"""

import asyncio
import json
import logging

from core.websocket import pubsub
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

BROADCAST_CHANNEL = "ws:notifications:broadcast"
USER_CHANNEL_PREFIX = "ws:notifications:user:"


async def user_notifications_handler(scope: dict, receive, send) -> None:
    """Push broadcast + user-specific notifications to authenticated user."""
    user_id = scope.get("user_id")
    if not user_id:
        await send({"type": "websocket.close", "code": 4001})
        return

    await send({"type": "websocket.accept"})

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
