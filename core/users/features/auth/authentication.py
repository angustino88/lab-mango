"""Production rejects pre-cutover tokens issued by password or LDAP login."""

from uuid import UUID

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.users.models import EntraIdentity


class EntraJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        if validated_token.get("auth_source") != "entra":
            raise AuthenticationFailed("Invalid authentication token.")
        user = super().get_user(validated_token)
        try:
            tenant = UUID(validated_token["entra_tid"])
            subject = UUID(validated_token["entra_oid"])
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AuthenticationFailed("Invalid authentication token.") from exc
        if not EntraIdentity.objects.filter(
            user_id=user.pk,
            tenant_id=tenant,
            object_id=subject,
        ).exists():
            raise AuthenticationFailed("Invalid authentication token.")
        return user


class EntraJWTScheme(SimpleJWTScheme):
    target_class = "core.users.features.auth.authentication.EntraJWTAuthentication"
    name = "jwtAuth"



