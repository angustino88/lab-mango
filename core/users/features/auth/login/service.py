import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from core.users.features.auth.login.ldap_service import ldap_auth

logger = logging.getLogger(__name__)

User = get_user_model()

INVALID_CREDENTIALS = "invalid_credentials"


class AuthenticationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def login(*, username: str, password: str) -> dict:
    """Authenticate a super admin user via LDAP (or Django auth) and return JWT tokens.

    Restricted: only super admin accounts (is_superuser=True) may log in via password/LDAP.

    Raises:
        AuthenticationError(INVALID_CREDENTIALS) — unavailable account, invalid credentials,
            or non-superadmin account.
    """
    if settings.ENTRA_SSO_ONLY:
        raise AuthenticationError(INVALID_CREDENTIALS)
    user = User.objects.filter(username=username).first()
    if user is None:
        raise AuthenticationError(INVALID_CREDENTIALS)

    if not user.is_active or not user.is_superuser:
        raise AuthenticationError(INVALID_CREDENTIALS)

    authenticated_user = ldap_auth(username=user.username, password=password)
    if (
        authenticated_user is None
        or not authenticated_user.is_active
        or not authenticated_user.is_superuser
        or authenticated_user.pk != user.pk
    ):
        raise AuthenticationError(INVALID_CREDENTIALS)

    refresh = RefreshToken.for_user(authenticated_user)
    return {
        "username": authenticated_user.username,
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "is_active": authenticated_user.is_active,
    }
