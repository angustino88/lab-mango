"""Regression tests: each WS route is served by its maintained, authorizing handler.

Four feature packages used to register a stale handler in ``__init__.py`` before
``handler.py``. The router dispatches to the first match, so the stale copies served
production traffic; the task-progress copy skipped the ownership check entirely.
"""

import asyncio

import pytest
from django.core.cache import cache

import core.websocket.features  # noqa: F401  (registers every route)
from core.websocket.router import _routes, register_route, ws_router
from core.websocket.task_ownership import register_task_owner


def test_every_route_is_registered_once_by_its_handler_module():
    patterns = [pattern.pattern for pattern, _ in _routes]
    assert len(patterns) == len(set(patterns)), "duplicate WebSocket routes shadow each other"
    for pattern, handler in _routes:
        assert handler.__module__.endswith(".handler"), f"{pattern.pattern} served by {handler.__module__}"


def test_registering_a_different_handler_for_an_existing_route_fails():
    async def impostor(scope, receive, send):  # pragma: no cover - never dispatched
        pass

    with pytest.raises(ValueError, match="already registered"):
        register_route("ws/tasks/{task_id}", impostor)


async def test_router_refuses_task_stream_to_a_user_who_does_not_own_it(asgi_send, asgi_receive):
    cache.set("task_owner:t-router-1", 1)
    try:
        scope = {"type": "websocket", "path": "/ws/tasks/t-router-1", "user_id": 2}
        await asyncio.wait_for(ws_router(scope, asgi_receive, asgi_send), timeout=2.0)
    finally:
        cache.delete("task_owner:t-router-1")

    assert not asgi_send.accepted()
    assert asgi_send.closed_with(4003)


async def test_router_streams_task_to_its_owner(asgi_send, asgi_receive):
    register_task_owner("t-router-2", 7)
    try:
        scope = {"type": "websocket", "path": "/ws/tasks/t-router-2", "user_id": 7}
        task = asyncio.create_task(ws_router(scope, asgi_receive, asgi_send))
        await asyncio.sleep(0.1)
        await asgi_receive.disconnect()
        await asyncio.wait_for(task, timeout=2.0)
    finally:
        cache.delete("task_owner:t-router-2")

    assert asgi_send.accepted()
