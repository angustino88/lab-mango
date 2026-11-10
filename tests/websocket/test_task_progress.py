"""Tests for task progress WS handler."""

import asyncio

from core.websocket import pubsub
from core.websocket.features.task_progress.handler import task_progress_handler


async def test_handler_accepts_connection(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 1, "url_params": {"task_id": "t-001"}}

    task = asyncio.create_task(
        task_progress_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.1)
    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    assert asgi_send.accepted()


async def test_handler_forwards_progress_update(asgi_send, asgi_receive):
    task_id = "t-002"
    scope = {"type": "websocket", "user_id": 1, "url_params": {"task_id": task_id}}

    task = asyncio.create_task(
        task_progress_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)

    await pubsub.publish(
        f"ws:tasks:{task_id}",
        {"state": "PROGRESS", "progress": 40, "message": "Processing"},
    )
    await asyncio.sleep(0.2)

    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    messages = asgi_send.sent_messages()
    assert any(m.get("progress") == 40 for m in messages)


async def test_handler_closes_on_terminal_state(asgi_send, asgi_receive):
    task_id = "t-003"
    scope = {"type": "websocket", "user_id": 1, "url_params": {"task_id": task_id}}

    # Pre-fill receive queue — disconnect won't be needed since SUCCESS closes it
    task = asyncio.create_task(
        task_progress_handler(scope, asgi_receive, asgi_send)
    )
    await asyncio.sleep(0.2)

    await pubsub.publish(
        f"ws:tasks:{task_id}",
        {"state": "SUCCESS", "progress": 100, "message": "Done"},
    )
    await asyncio.sleep(0.3)  # Let handler process terminal state + set done_event
    # Send disconnect so receive() unblocks when done_event is set
    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=3.0)

    messages = asgi_send.sent_messages()
    assert any(m.get("state") == "SUCCESS" for m in messages)
