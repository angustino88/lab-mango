"""Shared fixtures for WebSocket tests."""

import asyncio

import pytest
import redis.asyncio as aioredis
from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken

import core.websocket.publish_service as _publish_svc_module
import core.websocket.pubsub as _pubsub_module


@pytest.fixture(autouse=True)
async def reset_redis_pool():
    """Reset shared Redis connection pools between tests to avoid stale loop references."""
    # Reset before test
    _pubsub_module._redis_pool = None
    _publish_svc_module._sync_redis = None
    yield
    # Reset after test (cleanup)
    if _pubsub_module._redis_pool is not None:
        await _pubsub_module._redis_pool.aclose()
        _pubsub_module._redis_pool = None


@pytest.fixture
def valid_token(db):
    """Create a user and return (token_str, user_id)."""
    from core.users.models import User

    user = User.objects.create_user(username="wstest", password="testpass123")
    token = AccessToken.for_user(user)
    return str(token), user.pk


@pytest.fixture
def ws_scope():
    """WebSocket ASGI scope factory."""

    def _make(path="/ws/test", token=None, **kwargs):
        qs = f"token={token}" if token else ""
        return {
            "type": "websocket",
            "path": path,
            "query_string": qs.encode(),
            "headers": [],
            **kwargs,
        }

    return _make


class ASGISendCollector:
    """Collects ASGI send() calls for test assertions."""

    def __init__(self):
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)

    def accepted(self) -> bool:
        return any(e["type"] == "websocket.accept" for e in self.events)

    def closed_with(self, code: int) -> bool:
        return any(
            e["type"] == "websocket.close" and e.get("code") == code
            for e in self.events
        )

    def sent_messages(self) -> list[dict]:
        import json

        return [
            json.loads(e["text"])
            for e in self.events
            if e["type"] == "websocket.send"
        ]


class ASGIReceiveQueue:
    """Provides ASGI receive() backed by an asyncio.Queue."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()

    async def __call__(self) -> dict:
        return await self._queue.get()

    async def disconnect(self) -> None:
        await self._queue.put({"type": "websocket.disconnect"})

    async def send_text(self, text: str) -> None:
        await self._queue.put({"type": "websocket.receive", "text": text})


@pytest.fixture
def asgi_send():
    return ASGISendCollector()


@pytest.fixture
def asgi_receive():
    return ASGIReceiveQueue()


@pytest.fixture
async def redis_client():
    """Async Redis client for test pub/sub verification."""
    r = aioredis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    yield r
    await r.aclose()
