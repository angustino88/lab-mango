"""Authentication adapters always emit the shared API error envelope."""

import logging
from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from config.schema import ProjectAutoSchema
from core.common.api.api_views import AppAPIView
from core.common.api.correlation import get_request_id
from core.common.api.exceptions import api_exception_handler

logger = logging.getLogger(__name__)


class AuthenticationServiceUnavailable(APIException):
    status_code = 503
    default_detail = "Authentication is temporarily unavailable."
    default_code = "service_unavailable"


def auth_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, (RedisConnectionError, RedisTimeoutError)):
        logger.error(
            "Authentication throttle cache unavailable",
            extra={"request_id": get_request_id(context.get("request")), "error_type": type(exc).__name__},
        )
        response = api_exception_handler(AuthenticationServiceUnavailable(), context)
        if response is None:
            raise exc
        response.data["error"]["code"] = "service_unavailable"
        response.data["error"]["message"] = "Authentication is temporarily unavailable."
        response["Retry-After"] = "30"
        return response
    return api_exception_handler(exc, context)


class PublicAuthAutoSchema(ProjectAutoSchema):
    """Explicitly document operations without DRF authenticators, not CSRF exemptions."""

    def get_operation(self, path, path_regex, path_prefix, method, registry):
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        if operation is not None and not self.view.get_authenticators():
            operation["security"] = []
        return operation


class AuthAPIView(AppAPIView):
    def get_exception_handler(self):
        return auth_exception_handler

