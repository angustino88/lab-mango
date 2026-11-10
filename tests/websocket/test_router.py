"""Tests for WS path router."""

import pytest

from core.websocket.router import _routes, register_route, ws_router


@pytest.fixture(autouse=True)
def clean_routes():
    """Isolate route registry per test."""
    snapshot = list(_routes)
    _routes.clear()
    yield
    _routes.clear()
    _routes.extend(snapshot)


async def test_matching_route_invokes_handler(asgi_send):
    called: dict = {}

    async def handler(scope, receive, send):
        called["scope"] = scope

    register_route("ws/test", handler)
    scope = {"path": "/ws/test", "type": "websocket"}
    await ws_router(scope, None, asgi_send)

    assert "scope" in called


async def test_route_with_params(asgi_send):
    captured: dict = {}

    async def handler(scope, receive, send):
        captured.update(scope.get("url_params", {}))

    register_route("ws/equipment/{bench_id}", handler)
    scope = {"path": "/ws/equipment/42", "type": "websocket"}
    await ws_router(scope, None, asgi_send)

    assert captured == {"bench_id": "42"}


async def test_no_match_returns_4004(asgi_send):
    scope = {"path": "/ws/nonexistent", "type": "websocket"}
    await ws_router(scope, None, asgi_send)

    assert asgi_send.closed_with(4004)
