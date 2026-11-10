"""Tests for sync publish service utility."""

import asyncio

from core.websocket import pubsub
from core.websocket.publish_service import (
    publish_dashboard_status_update,
    publish_equipment_update,
    publish_monitoring_update,
    publish_notification,
    publish_task_progress,
)


async def test_publish_equipment_update():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:equipment:5"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    publish_equipment_update(
        bench_id=5, equipment_id=42, equipment_type="computer", status="offline"
    )

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["type"] == "equipment_status"
    assert received[0]["equipment_id"] == 42
    assert received[0]["status"] == "offline"


async def test_publish_monitoring_update():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:monitoring:3"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    publish_monitoring_update(bench_id=3, event_type="sensor_reading", data={"temp": 25})

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["type"] == "monitoring_update"
    assert received[0]["event_type"] == "sensor_reading"


async def test_publish_dashboard_status_update():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:monitoring:dashboard"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    publish_dashboard_status_update(
        event_type="computer_status_change",
        data={"computer_id": 99, "status": "active", "bench_id": 7},
    )

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["type"] == "monitoring_update"
    assert received[0]["event_type"] == "computer_status_change"
    assert received[0]["data"]["computer_id"] == 99


async def test_publish_notification_broadcasts():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:notifications:broadcast"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    publish_notification("Hello world", message_type="info")

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["message"] == "Hello world"


async def test_publish_notification_targets_user():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:notifications:user:7"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    publish_notification("Hi user", target_user_id=7)

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["message"] == "Hi user"


async def test_publish_task_progress():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:tasks:abc-123"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    publish_task_progress("abc-123", 50, "Halfway done")

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["progress"] == 50
    assert received[0]["message"] == "Halfway done"
