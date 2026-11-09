"""Agent discovery errors come from real default authenticators and throttles."""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from jsonschema import validate
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.agents.api.views import AgentInfoAPIView


def document():
    return SchemaGenerator(patterns=[path("agent/info", AgentInfoAPIView.as_view())]).get_schema(public=True)


def assert_error(response, status, code):
    schema = document()
    operation = schema["paths"]["/agent/info"]["get"]
    assert set(operation["responses"]) == {"200", "401", "429"}
    assert operation["operationId"] == "get_agent_info"
    assert response.status_code == status
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == code
    validate(
        response.data,
        {
            **operation["responses"][str(status)]["content"]["application/json"]["schema"],
            "components": schema["components"],
        },
    )


@pytest.mark.parametrize("authorization", ["Bearer", "Bearer synthetic-invalid-token"])
def test_info_allows_anonymous_but_rejects_invalid_bearer(authorization):
    cache.clear()
    factory = APIRequestFactory()
    assert AgentInfoAPIView.authentication_classes == [JWTAuthentication, SessionAuthentication]
    assert AgentInfoAPIView.as_view()(factory.get("/agent/info")).status_code == 200
    response = AgentInfoAPIView.as_view()(factory.get("/agent/info", HTTP_AUTHORIZATION=authorization))
    assert_error(response, 401, "unauthenticated")
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_info_safe_session_get_does_not_invent_a_csrf_error():
    raw = APIRequestFactory(enforce_csrf_checks=True).get("/agent/info")
    raw.user = get_user_model()(pk=1, is_active=True)
    # Safe GET bypasses CSRF: do not invent a 403 on this operation.
    response = AgentInfoAPIView.as_view()(raw)
    assert response.status_code == 200


@pytest.mark.parametrize("authenticated,throttle_class", [(False, AnonRateThrottle), (True, UserRateThrottle)])
def test_info_configured_throttle_is_reachable(authenticated, throttle_class):
    cache.clear()
    try:
        view = AgentInfoAPIView()
        raw = APIRequestFactory().get("/agent/info")
        if authenticated:
            force_authenticate(raw, user=get_user_model()(pk=1))
        request = view.initialize_request(raw)
        assert view.throttle_classes == [AnonRateThrottle, UserRateThrottle]
        throttle = throttle_class()
        key = throttle.get_cache_key(request, view)
        cache.set(key, [throttle.timer()] * throttle.num_requests, throttle.duration)
        response = AgentInfoAPIView.as_view()(raw)
        assert_error(response, 429, "rate_limited")
        assert int(response["Retry-After"]) > 0
    finally:
        cache.clear()
