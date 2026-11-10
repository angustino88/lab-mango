"""WebSocket path router — maps URL paths to handler functions."""

import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Route registry: list of (pattern, handler_func)
# Populated by register_route() at import time
_routes: list[tuple[re.Pattern, Callable[..., Coroutine[Any, Any, None]]]] = []


def register_route(pattern: str, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
    """Register a WS handler for a URL pattern. Patterns use {name} for params."""
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    compiled = re.compile(f"^{regex}$")
    for existing, existing_handler in _routes:
        if existing.pattern == compiled.pattern and existing_handler is not handler:
            # The router dispatches to the first match, so a duplicate would silently
            # shadow one handler (a stale copy once bypassed object authorization).
            raise ValueError(f"WebSocket route {pattern!r} is already registered by {existing_handler.__module__}.")
        if existing.pattern == compiled.pattern:
            return
    _routes.append((compiled, handler))


async def ws_router(scope: dict, receive, send) -> None:
    """Match scope["path"] against registered routes, invoke handler."""
    path = scope.get("path", "").strip("/")

    for pattern, handler in _routes:
        match = pattern.match(path)
        if match:
            scope["url_params"] = match.groupdict()
            await handler(scope, receive, send)
            return

    # No route matched — reject
    logger.debug("WS path not found: %s", path)
    await send({"type": "websocket.close", "code": 4004})
