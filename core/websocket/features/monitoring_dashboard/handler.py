"""WS handler: monitoring dashboard updates — ws/monitoring/{bench_id} and /dashboard."""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async

from core.websocket import pubsub
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ws:monitoring:"


@sync_to_async
def _can_view_monitoring(user_id: int, bench_id: str | None, is_dashboard: bool) -> bool:
    """ARCH-001: Verify user can view the monitoring dashboard or specific bench."""
    if is_dashboard:
        return True  # Assuming authenticated users can view the global dashboard

    try:
        from core.labs.models.resource.bench.bench import Bench
        return Bench.objects.filter(pk=bench_id, deleted_at__isnull=True).exists()
    except Exception:
        return False


async def monitoring_dashboard_handler(scope: dict, receive, send) -> None:
    """Push monitoring updates for a specific lab or all-labs dashboard."""
    bench_id = scope.get("url_params", {}).get("bench_id")
    user_id = scope.get("user_id")
    path = str(scope.get("path", "")).strip("/")
    is_dashboard = path.endswith("ws/monitoring/dashboard")

    if not is_dashboard and (not bench_id or not str(bench_id).isdigit()):
        await send({"type": "websocket.close", "code": 4003})
        return

    if not user_id:
        await send({"type": "websocket.close", "code": 4001})
        return

    # ARCH-001: Object-level authorization
    if not await _can_view_monitoring(user_id, str(bench_id) if bench_id else None, is_dashboard):
        logger.warning(f"User {user_id} denied WS access to monitoring stream")
        await send({"type": "websocket.close", "code": 4003})
        return

    await send({"type": "websocket.accept"})
    channel = f"{CHANNEL_PREFIX}dashboard" if is_dashboard else f"{CHANNEL_PREFIX}{bench_id}"
    listen_task = asyncio.create_task(_listen_redis(send, channel))

    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
    except Exception:
        logger.debug("Monitoring WS disconnected (bench=%s)", bench_id, exc_info=True)
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass


async def _listen_redis(send, channel: str) -> None:
    """Subscribe to Redis and forward monitoring updates to WS client."""
    try:
        async for data in pubsub.subscribe(channel):
            await send({"type": "websocket.send", "text": json.dumps(data)})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("Redis subscription error (%s)", channel, exc_info=True)


register_route("ws/monitoring/dashboard", monitoring_dashboard_handler)
register_route("ws/monitoring/{bench_id}", monitoring_dashboard_handler)
