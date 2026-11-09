"""
ASGI config — Uvicorn serves both HTTP and WebSocket on port 8000.

HTTP  → Django ASGI application
WebSocket → JWT middleware → WS router
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

django_app = get_asgi_application()

# Import WS modules at module level (after Django app init) to trigger route registration
import core.websocket.features  # noqa: F401, E402
from core.websocket.middleware import jwt_auth_middleware  # noqa: E402
from core.websocket.router import ws_router  # noqa: E402


async def lifespan_application(scope, receive, send):
    """Minimal lifespan responder so Uvicorn boots without warning noise."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def application(scope, receive, send):
    """Root ASGI application: dispatch by connection type."""
    if scope["type"] == "lifespan":
        await lifespan_application(scope, receive, send)
    elif scope["type"] == "http":
        await django_app(scope, receive, send)
    elif scope["type"] == "websocket":
        await jwt_auth_middleware(scope, receive, send, ws_router)
    else:
        raise ValueError(f"Unknown ASGI scope type: {scope['type']}")
