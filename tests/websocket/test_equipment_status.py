"""Tests for equipment status WS handler."""

import asyncio

from core.websocket import pubsub
from core.websocket.features.equipment_status.handler import (
    equipment_status_handler,
)


async def test_handler_accepts_connection(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 1, "url_params": {"bench_id": "10"}}

    task = asyncio.create_task(
        equipment_status_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.1)
    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    assert asgi_send.accepted()


async def test_handler_receives_lab_scoped_message(asgi_send, asgi_receive):
    bench_id = "10"
    scope = {"type": "websocket", "user_id": 1, "url_params": {"bench_id": bench_id}}

    task = asyncio.create_task(
        equipment_status_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)

    await pubsub.publish(
        f"ws:equipment:{bench_id}",
        {"type": "equipment_status", "equipment_id": 5, "status": "online"},
    )
    await asyncio.sleep(0.2)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    messages = asgi_send.sent_messages()
    assert any(m.get("equipment_id") == 5 for m in messages)


async def test_handler_ignores_other_lab_messages(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 1, "url_params": {"bench_id": "10"}}

    task = asyncio.create_task(
        equipment_status_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)

    # Publish to different lab
    await pubsub.publish(
        "ws:equipment:99",
        {"type": "equipment_status", "equipment_id": 99},
    )
    await asyncio.sleep(0.2)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    messages = asgi_send.sent_messages()
    assert not any(m.get("equipment_id") == 99 for m in messages)
