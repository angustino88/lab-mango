"""WS handler: equipment status updates — ws/equipment/{bench_id}/"""

import asyncio
import json
import logging

from core.websocket import pubsub
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ws:equipment:"


async def equipment_status_handler(scope: dict, receive, send) -> None:
    """Push equipment status changes for a specific lab."""
    bench_id = scope.get("url_params", {}).get("bench_id")
    if not bench_id or not str(bench_id).isdigit():
        await send({"type": "websocket.close", "code": 4003})
        return

    await send({"type": "websocket.accept"})
    channel = f"{CHANNEL_PREFIX}{bench_id}"
    listen_task = asyncio.create_task(_listen_redis(send, channel))

    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
    except Exception:
        logger.debug("Equipment WS disconnected (bench=%s)", bench_id, exc_info=True)
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass


async def _listen_redis(send, channel: str) -> None:
    """Subscribe to Redis and forward equipment updates to WS client."""
    try:
        async for data in pubsub.subscribe(channel):
            await send({"type": "websocket.send", "text": json.dumps(data)})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("Redis subscription error (%s)", channel, exc_info=True)


register_route("ws/equipment/{bench_id}", equipment_status_handler)
