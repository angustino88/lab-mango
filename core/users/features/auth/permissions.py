"""Require CSRF even when cookie credentials are used without a session."""

from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class CookieCSRFPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        try:
            SessionAuthentication().enforce_csrf(request)
        except PermissionDenied as exc:
            raise PermissionDenied("CSRF verification failed.") from exc
        return True
