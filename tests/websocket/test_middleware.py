"""Tests for JWT WebSocket authentication middleware."""

import pytest

from core.websocket.middleware import jwt_auth_middleware


async def _noop_app(scope, receive, send):
    """Dummy app that records scope."""
    scope["_reached"] = True


@pytest.mark.django_db
async def test_valid_token_passes_through(valid_token, ws_scope, asgi_send):
    token_str, user_id = valid_token
    scope = ws_scope(token=token_str)

    await jwt_auth_middleware(scope, None, asgi_send, _noop_app)

    assert str(scope.get("user_id")) == str(user_id)
    assert scope.get("_reached") is True


async def test_missing_token_rejects(ws_scope, asgi_send):
    scope = ws_scope(token=None)

    await jwt_auth_middleware(scope, None, asgi_send, _noop_app)

    assert asgi_send.closed_with(4001)
    assert not scope.get("_reached")


@pytest.mark.django_db
async def test_invalid_token_rejects(ws_scope, asgi_send):
    scope = ws_scope(token="invalid.jwt.token")

    await jwt_auth_middleware(scope, None, asgi_send, _noop_app)

    assert asgi_send.closed_with(4001)
