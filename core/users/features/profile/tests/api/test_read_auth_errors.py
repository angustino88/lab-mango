"""Profile read authentication failures use the deployed JWT/session stack."""

import pytest
from asgiref.sync import async_to_sync
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from jsonschema import validate
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.users.features.profile.avatar.api import UserAvatarView
from core.users.features.profile.get_me.api import GetMeView


@pytest.mark.parametrize(
    "view_class,route,operation_id",
    [
        (UserAvatarView, "users/avatar", "users_avatar_retrieve"),
        (GetMeView, "users/me", "users_me_retrieve"),
    ],
)
@pytest.mark.parametrize("authorization", [None, "Bearer", "Bearer synthetic-invalid-token"])
def test_read_documents_actual_authentication_failure(view_class, route, operation_id, authorization):
    assert view_class.authentication_classes == [JWTAuthentication, SessionAuthentication]
    headers = {} if authorization is None else {"HTTP_AUTHORIZATION": authorization}
    response = async_to_sync(view_class.as_view())(APIRequestFactory().get("/" + route, **headers))
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == "unauthenticated"
    schema = SchemaGenerator(patterns=[path(route, view_class.as_view())]).get_schema(public=True)
    operation = schema["paths"]["/" + route]["get"]
    assert operation["operationId"] == operation_id
    assert set(operation["responses"]) == {"200", "401"}
    validate(
        response.data,
        {**operation["responses"]["401"]["content"]["application/json"]["schema"], "components": schema["components"]},
    )
