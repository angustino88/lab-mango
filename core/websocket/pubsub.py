"""Async Redis pub/sub service for WebSocket broadcasting."""

import json
import logging
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from django.conf import settings

logger = logging.getLogger(__name__)

_redis_pool: aioredis.ConnectionPool | None = None


def _get_redis_url() -> str:
    """Redis URL from CELERY_BROKER_URL (same Redis instance)."""
    return settings.CELERY_BROKER_URL


async def get_redis() -> aioredis.Redis:
    """Get async Redis client (lazy-init connection pool)."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            _get_redis_url(),
            decode_responses=True,
        )
    return aioredis.Redis(connection_pool=_redis_pool)


async def publish(channel: str, data: dict) -> int:
    """Publish JSON message to Redis channel. Returns subscriber count."""
    r = await get_redis()
    return await r.publish(channel, json.dumps(data))


async def subscribe(channel: str) -> AsyncIterator[dict]:
    """Subscribe to Redis channel, yield parsed JSON messages."""
    r = await get_redis()
    ps = r.pubsub()
    await ps.subscribe(channel)
    try:
        async for msg in ps.listen():
            if msg["type"] == "message":
                try:
                    yield json.loads(msg["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Invalid JSON on channel %s", channel)
    finally:
        await ps.unsubscribe(channel)
        await ps.aclose()
