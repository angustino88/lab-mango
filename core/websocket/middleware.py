"""JWT authentication middleware for WebSocket connections."""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError

logger = logging.getLogger(__name__)

WS_CLOSE_AUTH_FAILED = 4001


async def jwt_auth_middleware(scope: dict, receive, send, app) -> None:
    """Authenticate WS connection via ?token= query param, then delegate to app."""
    # ASGI spec requires consuming the websocket.connect event first
    if receive is not None:
        await receive()
    token = _extract_token(scope)
    if not token:
        await _reject(send, WS_CLOSE_AUTH_FAILED)
        return

    user_id = await database_sync_to_async(_validate_token)(token)
    if user_id is None:
        await _reject(send, WS_CLOSE_AUTH_FAILED)
        return

    scope["user_id"] = user_id
    await app(scope, receive, send)


def _extract_token(scope: dict) -> str | None:
    qs = parse_qs(scope.get("query_string", b"").decode())
    return qs.get("token", [None])[0]


def _validate_token(token: str) -> int | None:
    """Validate JWT and return active user_id, or None on failure."""
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        if settings.ENTRA_SSO_ONLY:
            authentication = import_string(settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"][0])()
            return authentication.get_user(authentication.get_validated_token(token)).pk
        access_token = AccessToken(token)  # type: ignore[arg-type]
        user_id = access_token["user_id"]

        # Verify the user is still active in the database (ARCH-010)
        User = get_user_model()
        if not User.objects.filter(pk=user_id, is_active=True).exists():
            return None
        return user_id
    except (AuthenticationFailed, TokenError, ValueError, KeyError):
        logger.debug("WS JWT validation failed")
        return None


async def _reject(send, code: int) -> None:
    """Reject WebSocket connection with close code."""
    await send({"type": "websocket.close", "code": code})
