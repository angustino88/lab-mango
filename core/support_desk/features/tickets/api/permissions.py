"""Permission classes for Support Desk API views."""

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from core.support_desk.features.tickets.application.policies import (
    is_support_admin,
    is_support_agent,
)


class IsSupportAdmin(BasePermission):
    """Allows access only to support administrators."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated and is_support_admin(request.user))


class IsSupportAgent(BasePermission):
    """Allows access to support agents and administrators."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated and is_support_agent(request.user))


class IsSupportRequester(BasePermission):
    """Allows access to any authenticated requester."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated)
