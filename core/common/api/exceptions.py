"""Global DRF exception mapping to the standard API error envelope."""

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.common.domain.errors import (
    BadRequest,
    Conflict,
    DomainError,
    Forbidden,
    NotFound,
)

from .correlation import REQUEST_ID_HEADER, get_request_id

_ERRORS: dict[int, tuple[str, str]] = {
    status.HTTP_400_BAD_REQUEST: ("malformed_request", "The request is invalid."),
    status.HTTP_401_UNAUTHORIZED: ("unauthenticated", "Authentication is required."),
    status.HTTP_403_FORBIDDEN: ("permission_denied", "You do not have permission to perform this action."),
    status.HTTP_404_NOT_FOUND: ("not_found", "The requested resource was not found."),
    status.HTTP_409_CONFLICT: ("conflict", "The request conflicts with the current resource state."),
    status.HTTP_422_UNPROCESSABLE_ENTITY: ("validation_failed", "One or more fields are invalid."),
    status.HTTP_429_TOO_MANY_REQUESTS: ("rate_limited", "Too many requests. Please try again later."),
}


def _domain_status(exc: DomainError) -> int:
    explicit_status = getattr(exc, "status_code", None)
    if isinstance(explicit_status, int):
        return explicit_status
    if isinstance(exc, NotFound):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, Forbidden):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, Conflict):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, BadRequest):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def _error_response(
    request: Any,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str | None]] | None = None,
) -> Response:
    request_id = get_request_id(request)
    return Response(
        {"error": {"code": code, "message": message, "details": details or [], "request_id": request_id}},
        status=status_code,
        headers={REQUEST_ID_HEADER: request_id},
    )


def _map_business_exception(exc: Exception, request: Any) -> Response | None:
    """Render domain and Django ORM/validation errors; None for anything else."""
    if isinstance(exc, DomainError):
        details = _validation_details(exc.details) if exc.details else []
        return _error_response(
            request,
            status_code=_domain_status(exc),
            code=exc.code,
            message=exc.message,
            details=details,
        )
    if isinstance(exc, ObjectDoesNotExist):
        code, message = _ERRORS[status.HTTP_404_NOT_FOUND]
        return _error_response(request, status_code=status.HTTP_404_NOT_FOUND, code=code, message=message)
    if isinstance(exc, DjangoValidationError):
        errors = exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        return _error_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_failed",
            message="One or more fields are invalid.",
            details=_validation_details(errors),
        )
    return None


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Convert recognized DRF and business exceptions into the standard error response."""
    mapped = _map_business_exception(exc, context.get("request"))
    if mapped is not None:
        return mapped
    response = drf_exception_handler(exc, context)
    if response is None:
        request_id = get_request_id(context.get("request"))
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": [],
                    "request_id": request_id,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={REQUEST_ID_HEADER: request_id},
        )

    request = context.get("request")
    request_id = get_request_id(request)

    if isinstance(exc, exceptions.ValidationError):
        status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY
        code = "validation_failed"
        message = "One or more fields are invalid."
        details = _validation_details(response.data)
    elif isinstance(exc, exceptions.ParseError):
        status_code = status.HTTP_400_BAD_REQUEST
        code = "malformed_request"
        message = "Request body is not valid."
        details = []
    elif isinstance(exc, exceptions.UnsupportedMediaType):
        status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        code = "unsupported_media_type"
        message = "The request media type is not supported."
        details = []
    else:
        status_code = response.status_code
        code, message = _ERRORS.get(
            status_code,
            ("api_error", "The request could not be completed."),
        )
        details = []
        if status_code == status.HTTP_400_BAD_REQUEST:
            code = "malformed_request"

    response.data = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }
    response.status_code = status_code
    response[REQUEST_ID_HEADER] = request_id
    return response


def _validation_details(errors: Any, prefix: str = "") -> list[dict[str, str | None]]:
    """Flatten DRF's nested validation errors into stable field details."""
    if isinstance(errors, Mapping):
        details = []
        for field, value in errors.items():
            field_path = f"{prefix}.{field}" if prefix else str(field)
            details.extend(_validation_details(value, field_path))
        return details
    if isinstance(errors, (list, tuple)):
        details = []
        for index, value in enumerate(errors):
            if prefix and hasattr(value, "code"):
                details.extend(_validation_details(value, prefix))
            else:
                item_path = f"{prefix}[{index}]" if prefix else str(index)
                details.extend(_validation_details(value, item_path))
        return details
    return [
        {
            "field": prefix or None,
            "code": str(getattr(errors, "code", "invalid")),
            "message": str(errors),
        }
    ]
