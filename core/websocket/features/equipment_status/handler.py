"""WS handler: equipment status updates — ws/equipment/{bench_id}/"""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async

from core.websocket import pubsub
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ws:equipment:"


@sync_to_async
def _can_view_bench(user_id: int, bench_id: str) -> bool:
    """ARCH-001: Verify user can view this bench."""
    try:
        from core.labs.models.resource.bench.bench import Bench
        return Bench.objects.filter(pk=bench_id, deleted_at__isnull=True).exists()
    except Exception:
        return False


async def equipment_status_handler(scope: dict, receive, send) -> None:
    """Push equipment status changes for a specific lab."""
    bench_id = scope.get("url_params", {}).get("bench_id")
    user_id = scope.get("user_id")

    if not bench_id or not str(bench_id).isdigit() or not user_id:
        await send({"type": "websocket.close", "code": 4003})
        return

    # ARCH-001: Object-level authorization
    if not await _can_view_bench(user_id, str(bench_id)):
        logger.warning(f"User {user_id} denied WS access to bench {bench_id}")
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
