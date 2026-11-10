"""Tests for per-user notification WS handler."""

import asyncio

from core.websocket import pubsub
from core.websocket.features.user_notifications.handler import (
    user_notifications_handler,
)


async def test_handler_accepts_authenticated_connection(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 42}

    task = asyncio.create_task(
        user_notifications_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.1)
    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    assert asgi_send.accepted()


async def test_handler_rejects_unauthenticated(asgi_send, asgi_receive):
    scope = {"type": "websocket"}  # No user_id

    task = asyncio.create_task(
        user_notifications_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.wait_for(task, timeout=2.0)

    assert asgi_send.closed_with(4001)


async def test_handler_receives_broadcast_message(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 99}

    task = asyncio.create_task(
        user_notifications_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)

    await pubsub.publish(
        "ws:notifications:broadcast",
        {"type": "notification", "message": "global"},
    )
    await asyncio.sleep(0.2)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    messages = asgi_send.sent_messages()
    assert any(m.get("message") == "global" for m in messages)


async def test_handler_receives_targeted_message(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 10}

    task = asyncio.create_task(
        user_notifications_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)

    await pubsub.publish(
        "ws:notifications:user:10",
        {"type": "notification", "message": "targeted"},
    )
    await asyncio.sleep(0.2)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    messages = asgi_send.sent_messages()
    assert any(m.get("message") == "targeted" for m in messages)
