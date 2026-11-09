"""WS handler: Celery task progress — ws/tasks/{task_id}/"""

import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from django.core.cache import cache

from core.websocket import pubsub
from core.websocket.router import register_route

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ws:tasks:"
TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED"}


@sync_to_async
def _can_view_task(user_id: int, task_id: str) -> bool:
    """ARCH-001: Bind task IDs to their initiating actor.
    If the task owner was set in cache when enqueued, verify it.
    If not explicitly tracked, we default to deny to enforce the new secure boundary.
    """
    owner_id = cache.get(f"task_owner:{task_id}")
    # If the task owner is known and matches, allow.
    # If None, the task wasn't securely enqueued with an owner -> deny.
    return str(owner_id) == str(user_id)


async def task_progress_handler(scope: dict, receive, send) -> None:
    """Push Celery task progress/state updates to connected client."""
    task_id = scope.get("url_params", {}).get("task_id")
    user_id = scope.get("user_id")

    if not task_id or not user_id:
        await send({"type": "websocket.close", "code": 4003})
        return

    # ARCH-001: Object-level authorization
    if not await _can_view_task(user_id, task_id):
        logger.warning(f"User {user_id} denied WS access to task {task_id}")
        await send({"type": "websocket.close", "code": 4003})
        return

    await send({"type": "websocket.accept"})
    channel = f"{CHANNEL_PREFIX}{task_id}"

    done_event = asyncio.Event()
    listen_task = asyncio.create_task(_listen_redis(send, channel, done_event))

    try:
        while not done_event.is_set():
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
    except Exception:
        logger.debug("Task WS disconnected (task=%s)", task_id, exc_info=True)
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass
        # Send server-initiated close after terminal state
        if done_event.is_set():
            await send({"type": "websocket.close", "code": 1000})


async def _listen_redis(send, channel: str, done_event: asyncio.Event) -> None:
    """Subscribe to Redis and forward task updates to WS client."""
    try:
        async for data in pubsub.subscribe(channel):
            await send({"type": "websocket.send", "text": json.dumps(data)})
            # Auto-signal close after terminal state
            if data.get("state") in TERMINAL_STATES:
                done_event.set()
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error("Redis subscription error (%s)", channel, exc_info=True)


register_route("ws/tasks/{task_id}", task_progress_handler)
