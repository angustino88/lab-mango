"""Tests for Celery signal → Redis bridge."""

import asyncio

from core.websocket import pubsub
from core.websocket.celery_signals import on_task_failure, on_task_postrun, on_task_prerun


async def test_task_prerun_publishes_started():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:tasks:task-001"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    on_task_prerun(task_id="task-001", task=None, args=[], kwargs={})

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["state"] == "STARTED"
    assert received[0]["task_id"] == "task-001"


async def test_task_postrun_publishes_success():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:tasks:task-002"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    on_task_postrun(
        task_id="task-002",
        task=None,
        args=[],
        kwargs={},
        retval="result-data",
        state="SUCCESS",
    )

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["state"] == "SUCCESS"
    assert received[0]["task_id"] == "task-002"


async def test_task_failure_publishes_failure():
    received: list[dict] = []

    async def listener():
        async for msg in pubsub.subscribe("ws:tasks:task-003"):
            received.append(msg)
            break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.1)

    on_task_failure(
        task_id="task-003",
        exception=ValueError("Something went wrong"),
        traceback=None,
        einfo=None,
        args=[],
        kwargs={},
        sender=None,
    )

    await asyncio.wait_for(task, timeout=2.0)
    assert received[0]["state"] == "FAILURE"
    assert "Something went wrong" in (received[0].get("result") or "")
