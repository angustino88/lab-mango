from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework import exceptions, status
from rest_framework.exceptions import ErrorDetail
from rest_framework.request import Request

from core.common.api.correlation import RequestCorrelationMiddleware
from core.common.api.exceptions import api_exception_handler


def _context(request):
    return {"request": Request(request), "view": None}


def test_correlation_middleware_preserves_canonical_incoming_id_and_sets_header():
    request_id = "0123456789abcdef0123456789abcdef"
    request = RequestFactory().get("/api/labs", HTTP_X_REQUEST_ID=request_id)
    middleware = RequestCorrelationMiddleware(lambda _: HttpResponse("ok"))

    response = middleware(request)

    assert request.request_id == request_id
    assert response["X-Request-ID"] == request_id


def test_correlation_middleware_replaces_invalid_incoming_id():
    request = RequestFactory().get("/api/labs", HTTP_X_REQUEST_ID="bad\nid")
    middleware = RequestCorrelationMiddleware(lambda _: HttpResponse("ok"))

    response = middleware(request)

    assert len(request.request_id) == 32
    assert response["X-Request-ID"] == request.request_id


def test_validation_exception_maps_to_422_error_envelope():
    request_id = "0123456789abcdef0123456789abcdef"
    request = RequestFactory().post("/api/labs", HTTP_X_REQUEST_ID=request_id)
    error_response = api_exception_handler(
        exceptions.ValidationError({"email": ["Enter a valid email."]}),
        _context(request),
    )

    assert error_response is not None
    assert error_response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert error_response["X-Request-ID"] == request_id
    assert error_response.data == {
        "error": {
            "code": "validation_failed",
            "message": "One or more fields are invalid.",
            "details": [{"field": "email", "code": "invalid", "message": "Enter a valid email."}],
            "request_id": request_id,
        }
    }


def test_nested_array_validation_fields_use_bracket_indexes():
    request = RequestFactory().post("/api/labs")
    error_response = api_exception_handler(
        exceptions.ValidationError({"items": [{"quantity": [ErrorDetail("Must be positive.", code="min_value")]}]}),
        _context(request),
    )

    assert error_response is not None
    assert error_response.data["error"]["details"] == [
        {"field": "items[0].quantity", "code": "min_value", "message": "Must be positive."}
    ]


def test_parse_error_maps_to_400_without_exposing_parser_detail():
    request_id = "fedcba9876543210fedcba9876543210"
    request = RequestFactory().post("/api/labs", HTTP_X_REQUEST_ID=request_id)
    error_response = api_exception_handler(exceptions.ParseError("internal parser details"), _context(request))

    assert error_response is not None
    assert error_response.status_code == status.HTTP_400_BAD_REQUEST
    assert error_response.data["error"] == {
        "code": "malformed_request",
        "message": "Request body is not valid.",
        "details": [],
        "request_id": request_id,
    }


def test_not_authenticated_maps_to_error_envelope_and_correlated_header():
    request = RequestFactory().get("/api/labs/")
    error_response = api_exception_handler(exceptions.NotAuthenticated(), _context(request))

    assert error_response is not None
    assert error_response.status_code == status.HTTP_401_UNAUTHORIZED
    assert error_response["X-Request-ID"] == error_response.data["error"]["request_id"]
    assert error_response.data["error"]["code"] == "unauthenticated"


def test_not_found_exception_maps_to_generic_human_readable_message():
    request = RequestFactory().get("/api/labs/benches/999999")
    error_response = api_exception_handler(exceptions.NotFound(), _context(request))

    assert error_response is not None
    assert error_response.status_code == status.HTTP_404_NOT_FOUND
    error = error_response.data["error"]
    assert error == {
        "code": "not_found",
        "message": "The requested resource was not found.",
        "details": [],
        "request_id": error["request_id"],
    }
    assert len(error["request_id"]) == 32


def test_unexpected_exception_maps_to_sanitized_500_envelope():
    request_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    request = RequestFactory().get("/api/labs", HTTP_X_REQUEST_ID=request_id)
    error_response = api_exception_handler(RuntimeError("sensitive implementation detail"), _context(request))

    assert error_response is not None
    assert error_response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert error_response["X-Request-ID"] == request_id
    assert error_response.data["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "details": [],
        "request_id": request_id,
    }
