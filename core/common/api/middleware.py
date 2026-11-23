"""Technical HTTP middleware for API responses (BREACH-safe GZip compression)."""

from __future__ import annotations

from django.middleware.gzip import GZipMiddleware

# Endpoints that return bearer/refresh tokens, CSRF secrets, or auth credentials in the body
# are excluded from HTTP compression to mitigate BREACH side-channel attacks.
_AUTH_EXCLUDED_PREFIXES = (
    "/api/aad-login",
    "/api/refresh-token",
    "/api/logout",
    "/api/csrf-token",
    "/api/token",
    "/api/auth/",
)


class SafeGZipMiddleware(GZipMiddleware):
    """GZipMiddleware that skips compression on auth/token endpoints."""

    def process_response(self, request, response):
        path = getattr(request, "path", "") or ""
        if any(path.startswith(prefix) for prefix in _AUTH_EXCLUDED_PREFIXES):
            return response
        return super().process_response(request, response)
