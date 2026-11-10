"""Tests for broadcast notification WS handler."""

import asyncio

from core.websocket import pubsub
from core.websocket.features.broadcast_notifications.handler import (
    broadcast_notifications_handler,
)


async def test_handler_accepts_connection(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 1}

    task = asyncio.create_task(
        broadcast_notifications_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.1)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    assert asgi_send.accepted()


async def test_handler_forwards_broadcast_message(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 1}

    task = asyncio.create_task(
        broadcast_notifications_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)  # Wait for Redis subscription

    await pubsub.publish(
        "ws:notifications:broadcast",
        {"type": "notification", "message": "test broadcast"},
    )
    await asyncio.sleep(0.2)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    messages = asgi_send.sent_messages()
    assert any(m.get("message") == "test broadcast" for m in messages)
