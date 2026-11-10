"""Tests for the computing activity WS handler and publisher."""

import asyncio
import json
from unittest.mock import MagicMock, patch

from core.websocket import pubsub
from core.websocket.features.computing_activity.handler import computing_activity_handler
from core.websocket.publish_service import publish_computing_activity_update


async def test_handler_rejects_non_numeric_id(asgi_send, asgi_receive):
    scope = {"type": "websocket", "user_id": 1, "url_params": {"computing_id": "abc"}}

    await computing_activity_handler(scope, asgi_receive, asgi_send)

    assert not asgi_send.accepted()
    assert asgi_send.closed_with(4003)


async def test_handler_accepts_connection(asgi_send, asgi_receive, ws_computing_id):
    scope = {"type": "websocket", "user_id": 1, "url_params": {"computing_id": ws_computing_id}}

    task = asyncio.create_task(computing_activity_handler(scope, asgi_receive, asgi_send))
    await asyncio.sleep(0.1)
    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    assert asgi_send.accepted()


async def test_handler_receives_activity_event(asgi_send, asgi_receive, ws_computing_id):
    scope = {"type": "websocket", "user_id": 1, "url_params": {"computing_id": ws_computing_id}}

    task = asyncio.create_task(computing_activity_handler(scope, asgi_receive, asgi_send))
    await asyncio.sleep(0.2)
    await pubsub.publish(
        f"ws:computing:{ws_computing_id}",
        {"type": "computing_activity", "event_type": "computer_status_change", "data": {"status": "active"}},
    )
    await asyncio.sleep(0.2)
    await asgi_receive.disconnect()
    await asyncio.wait_for(task, timeout=2.0)

    assert any(m.get("event_type") == "computer_status_change" for m in asgi_send.sent_messages())


def test_publish_uses_per_computer_channel():
    redis_client = MagicMock()
    with patch("core.websocket.publish_service._get_sync_redis", return_value=redis_client):
        publish_computing_activity_update(computing_id=7, data={"status": "active"})

    channel, raw = redis_client.publish.call_args.args
    payload = json.loads(raw)
    assert channel == "ws:computing:7"
    assert payload["type"] == "computing_activity"
    assert payload["computer_id"] == 7
    assert payload["data"] == {"status": "active"}
