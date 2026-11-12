import hashlib
import logging
import secrets
from functools import lru_cache
from uuid import UUID

import jwt
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from jwt import PyJWKClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.users.models import EntraIdentity, EntraLoginChallenge, User
from core.users.public import BindEntraIdentityInput, bind_entra_identity, has_ever_been_bound

logger = logging.getLogger(__name__)

INVALID_SSO_TOKEN = "invalid_sso_token"


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, timeout=5, lifespan=300)


class AADAuthError(Exception):
    """Raised when AAD token validation fails for any reason."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _decode_id_token(id_token: str) -> dict:
    """Validate and decode an AAD RS256 JWT.

    Raises AADAuthError on any validation failure.
    """
    try:
        jwks_client = _jwks_client(settings.AAD_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.AAD_AUDIENCE,
            issuer=settings.AAD_ISSUER,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "tid", "oid", "nonce"]},
        )
        if UUID(payload["tid"]) != UUID(settings.AAD_TENANT_ID):
            raise ValueError("Invalid tenant")
        UUID(payload["oid"])
        if not isinstance(payload["nonce"], str) or not payload["nonce"] or not payload["sub"]:
            raise ValueError("Invalid identity claims")
        return payload
    except jwt.PyJWKClientConnectionError as exc:
        logger.warning("Entra JWKS connection failed")
        raise AADAuthError(INVALID_SSO_TOKEN) from exc
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        logger.info("Entra authentication rejected")
        raise AADAuthError(INVALID_SSO_TOKEN) from exc


def create_login_challenge() -> tuple[EntraLoginChallenge, str]:
    nonce = secrets.token_urlsafe(32)
    challenge = EntraLoginChallenge.objects.create(
        nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=timezone.now() + settings.AAD_LOGIN_CHALLENGE_LIFETIME,
    )
    return challenge, nonce


def _bind_identity_by_username(payload: dict) -> EntraIdentity | None:
    """Bind an unbound Entra subject to the one matching non-privileged user (first login only).

    Safeguards (owner decision 2026-11-12, option A); any failed check means no binding:
    * the UPN domain is in ``ENTRA_BIND_ALLOWED_DOMAINS``;
    * the account is a tenant member, not a guest (``#EXT#`` UPN or ``acct`` claim 1);
    * exactly one active local user matches, and it is not staff or superuser;
    * that user was never bound before (an unlinked account is re-bound only by an operator).
    Every binding is recorded in the role audit log by the lifecycle command; binding an old account
    is also logged as a warning for review.
    """
    preferred = payload.get("preferred_username")
    if not settings.ENTRA_BIND_BY_USERNAME or not isinstance(preferred, str) or not preferred.strip():
        return None
    preferred = preferred.strip()
    local_part, separator, domain = preferred.rpartition("@")
    if not separator or not local_part or domain.lower() not in set(settings.ENTRA_BIND_ALLOWED_DOMAINS):
        logger.info("Entra username binding refused: domain not allowed")
        return None
    if "#ext#" in preferred.lower() or payload.get("acct") == 1:
        logger.info("Entra username binding refused: guest account")
        return None
    users = list(
        User.objects.select_for_update().filter(Q(username__iexact=preferred) | Q(username__iexact=local_part))[:2]
    )
    if len(users) != 1:
        return None
    user = users[0]
    if not user.is_active or user.is_staff or user.is_superuser:
        return None
    if has_ever_been_bound(user.pk):
        logger.warning("Entra username binding refused: account was bound before", extra={"user_id": user.pk})
        return None
    result = bind_entra_identity(
        data=BindEntraIdentityInput(
            user_id=user.pk,
            tenant_id=UUID(payload["tid"]),
            object_id=UUID(payload["oid"]),
        ),
    )
    identity = EntraIdentity.objects.get(pk=result.identity_id)
    account_age = timezone.now() - user.date_joined
    if account_age.days >= settings.ENTRA_BIND_DORMANT_WARNING_DAYS:
        logger.warning(
            "Entra identity bound by username to an account older than the review threshold",
            extra={"user_id": user.pk, "account_age_days": account_age.days},
        )
    else:
        logger.info("Entra identity bound by username", extra={"user_id": user.pk})
    return identity


def aad_login(*, id_token: str, challenge_id: str) -> tuple[dict, User]:
    """Consume one browser-bound nonce and authenticate only explicitly bound identities."""
    payload = _decode_id_token(id_token)
    try:
        challenge_uuid = UUID(challenge_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AADAuthError(INVALID_SSO_TOKEN) from exc
    # Keep challenge consumption, identity binding, and routing publication in one transaction.
    with transaction.atomic():
        challenge = EntraLoginChallenge.objects.select_for_update().filter(pk=challenge_uuid).first()
        now = timezone.now()
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
            or not secrets.compare_digest(
                challenge.nonce_digest, hashlib.sha256(payload["nonce"].encode()).hexdigest()
            )
        ):
            raise AADAuthError(INVALID_SSO_TOKEN)
        identity = (
            EntraIdentity.objects.select_for_update()
            .filter(tenant_id=payload["tid"], object_id=payload["oid"])
            .first()
        )
        if identity is None:
            try:
                identity = _bind_identity_by_username(payload)
            except ValueError as exc:
                raise AADAuthError(INVALID_SSO_TOKEN) from exc
            if identity is None:
                raise AADAuthError(INVALID_SSO_TOKEN)
        user = User.objects.select_for_update().get(pk=identity.user_id)
        if not user.is_active:
            raise AADAuthError(INVALID_SSO_TOKEN)
        current_identity = EntraIdentity.objects.select_for_update().filter(pk=identity.pk, user_id=user.pk).first()
        if current_identity is None:
            raise AADAuthError(INVALID_SSO_TOKEN)
        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at"])
        # Recorded for the access review (dormant privileged accounts); the user row is already locked.
        User.objects.filter(pk=user.pk).update(last_login=now)
        refresh = RefreshToken.for_user(user)
        refresh["auth_source"] = "entra"
        refresh["entra_tid"] = str(current_identity.tenant_id)
        refresh["entra_oid"] = str(current_identity.object_id)
        logger.info("Entra authentication succeeded", extra={"user_id": user.pk})
        return {
            "username": user.username,
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "is_active": user.is_active,
        }, user
