"""WS handler: computing activity status changes — ws/computing/{computing_id}"""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async

from core.websocket import pubsub
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ws:computing:"


@sync_to_async
def _can_view_computing(user_id: int, computing_id: str) -> bool:
    """ARCH-001: Verify user can view this computing equipment."""
    try:
        from core.labs.models.resource.equipment.equipment import Equipment
        return Equipment.objects.filter(pk=computing_id, deleted_at__isnull=True).exists()
    except Exception:
        return False


async def computing_activity_handler(scope: dict, receive, send) -> None:
    """Push activity status changes for one computing equipment record."""
    computing_id = scope.get("url_params", {}).get("computing_id")
    user_id = scope.get("user_id")

    if not computing_id or not str(computing_id).isdigit() or not user_id:
        await send({"type": "websocket.close", "code": 4003})
        return

    # ARCH-001: Object-level authorization
    if not await _can_view_computing(user_id, str(computing_id)):
        logger.warning(f"User {user_id} denied WS access to computing equipment {computing_id}")
        await send({"type": "websocket.close", "code": 4003})
        return

    await send({"type": "websocket.accept"})
    channel = f"{CHANNEL_PREFIX}{computing_id}"
    listen_task = asyncio.create_task(_listen_redis(send, channel))

    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
    except Exception:
        logger.debug("Computing activity WS disconnected (computing=%s)", computing_id, exc_info=True)
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass


async def _listen_redis(send, channel: str) -> None:
    """Subscribe to Redis and forward computing activity updates to the WS client."""
    try:
        async for data in pubsub.subscribe(channel):
            await send({"type": "websocket.send", "text": json.dumps(data)})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("Redis subscription error (%s)", channel, exc_info=True)


register_route("ws/computing/{computing_id}", computing_activity_handler)
