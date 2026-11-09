"""Request correlation identifiers for API responses and logs."""

import re
import uuid
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse

from core.common.logging import set_request_id

_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id(request: Any) -> str:
    """Return the request's validated correlation identifier, creating one if absent."""
    request_id = getattr(request, "request_id", None)
    if isinstance(request_id, str) and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id

    meta = getattr(request, "META", {})
    candidate = meta.get("HTTP_X_REQUEST_ID", "") if isinstance(meta, dict) else ""
    request_id = (
        candidate if isinstance(candidate, str) and _REQUEST_ID_PATTERN.fullmatch(candidate) else uuid.uuid4().hex
    )
    try:
        request.request_id = request_id
    except AttributeError:
        pass
    return request_id


class RequestCorrelationMiddleware:
    """Validate or generate a request ID and expose it on the response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = get_request_id(request)
        setattr(request, "request_id", request_id)
        set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            set_request_id("-")
        response[REQUEST_ID_HEADER] = request_id
        return response
