"""Serialize refresh rotation and logout against the same outstanding-token row."""

from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from core.users.models import EntraIdentity


def _lock_token(raw_token: str) -> None:
    # SimpleJWT's constructor annotation says Token; its verified runtime API accepts encoded strings.
    payload = UntypedToken(raw_token).payload  # type: ignore[arg-type]
    row = OutstandingToken.objects.select_for_update().filter(jti=payload.get(api_settings.JTI_CLAIM)).first()
    if row is None:
        raise TokenError("Invalid refresh token")


def rotate_refresh(*, raw_token: str) -> dict[str, str]:
    with transaction.atomic():
        _lock_token(raw_token)
        refresh = RefreshToken(raw_token)  # type: ignore[arg-type]
        user = (
            get_user_model()
            .objects.select_for_update()
            .filter(
                **{api_settings.USER_ID_FIELD: refresh.get(api_settings.USER_ID_CLAIM)},
                is_active=True,
            )
            .first()
        )
        if user is None:
            raise TokenError("Invalid refresh token")
        if settings.ENTRA_SSO_ONLY:
            try:
                tenant = UUID(refresh["entra_tid"])
                subject = UUID(refresh["entra_oid"])
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise TokenError("Invalid refresh token") from exc
            if (
                refresh.get("auth_source") != "entra"
                or not EntraIdentity.objects.filter(
                    user=user,
                    tenant_id=tenant,
                    object_id=subject,
                ).exists()
            ):
                raise TokenError("Invalid refresh token")
        refresh.blacklist()
        replacement = RefreshToken.for_user(user)
        for claim in ("auth_source", "entra_tid", "entra_oid"):
            if claim in refresh:
                replacement[claim] = refresh[claim]
        return {"access": str(replacement.access_token), "refresh": str(replacement)}


def revoke_refresh(*, raw_token: str) -> None:
    with transaction.atomic():
        _lock_token(raw_token)
        RefreshToken(raw_token).blacklist()  # type: ignore[arg-type]
