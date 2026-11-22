"""Production rejects pre-cutover tokens issued by password or LDAP login."""

from uuid import UUID

from django.conf import settings
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.common.cache import get_namespace_version, safe_cache_get, safe_cache_set
from core.users.models import EntraIdentity

_USERS_ACCESS_CACHE_NAMESPACE = "users:access"


class EntraJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        if validated_token.get("auth_source") != "entra":
            raise AuthenticationFailed("Invalid authentication token.")
        try:
            tenant = UUID(validated_token["entra_tid"])
            subject = UUID(validated_token["entra_oid"])
            raw_user_id = validated_token.get("user_id")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AuthenticationFailed("Invalid authentication token.") from exc

        cache_key: str | None = None
        if getattr(settings, "API_AUTH_CACHE_ENABLED", False) and raw_user_id is not None:
            ns_ver = get_namespace_version(_USERS_ACCESS_CACHE_NAMESPACE)
            if ns_ver > 0:
                cache_key = f"users:entra_user:v{ns_ver}:{raw_user_id}:{tenant}:{subject}"
                cached_user = safe_cache_get(cache_key)
                if cached_user is not None:
                    return cached_user

        user = super().get_user(validated_token)
        if not EntraIdentity.objects.filter(
            user_id=user.pk,
            tenant_id=tenant,
            object_id=subject,
        ).exists():
            raise AuthenticationFailed("Invalid authentication token.")

        if cache_key is not None and getattr(user, "is_active", False):
            ttl = int(getattr(settings, "API_AUTH_CACHE_TTL", 120) or 120)
            safe_cache_set(cache_key, user, timeout=ttl)
        return user


class EntraJWTScheme(SimpleJWTScheme):
    target_class = "core.users.features.auth.authentication.EntraJWTAuthentication"
    name = "jwtAuth"



