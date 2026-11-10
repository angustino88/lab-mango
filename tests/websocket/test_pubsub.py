"""Tests for Redis pub/sub service."""

import asyncio

import redis.asyncio as aioredis
from django.conf import settings

from core.websocket import pubsub


async def test_publish_returns_subscriber_count():
    count = await pubsub.publish("ws:test:count", {"msg": "hello"})
    assert isinstance(count, int)


async def test_subscribe_receives_published_message():
    channel = "ws:test:sub"
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe(channel):
            received.append(msg)
            break  # Only need one

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.15)  # Let subscription establish

    await pubsub.publish(channel, {"key": "value"})
    await asyncio.wait_for(task, timeout=3.0)

    assert received == [{"key": "value"}]


async def test_subscribe_skips_invalid_json():
    """Non-JSON messages on channel are skipped, valid ones received."""
    channel = "ws:test:bad-json"
    r = aioredis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)

    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe(channel):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.15)

    await r.publish(channel, "not-json{{{")
    await r.publish(channel, '{"valid": true}')

    await asyncio.wait_for(task, timeout=3.0)
    assert received == [{"valid": True}]
    await r.aclose()
