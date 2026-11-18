"""Pytest support: the stub issuer in-process, without a JWKS server.

``stub_entra_environment(issuer)`` applies the local stub settings and makes the three production JWKS
lookups (ID-token login, delegated access tokens, routing sync) resolve keys from ``issuer``. The production
validators still run in full: only where the keys come from changes.

    from tools.stubs.testing import stub_entra_environment
    from tools.stubs.entra import StubIssuer

    issuer = StubIssuer.generate()
    with stub_entra_environment(issuer):
        token, nonce_secret = issuer.id_token(issuer.manifest.get("alice"))
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from django.test import override_settings

from tools.stubs.common import STUB_TENANT_ID, UPN_DOMAIN
from tools.stubs.entra import ISSUER_TEMPLATE, StubIssuer

JWKS_LOOKUPS = (
    "core.users.features.auth.aad_login.service._jwks_client",
    "core.users.features.auth.access_token._jwks_client",
    "core.routing.api.authentication._get_jwks_client",
)


class StubJWKClient:
    """Behaves like ``jwt.PyJWKClient`` for the calls the validators make."""

    def __init__(self, issuer: StubIssuer, *, unreachable: bool = False):
        self.issuer = issuer
        self.unreachable = unreachable

    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        if self.unreachable:
            raise jwt.PyJWKClientConnectionError("stub JWKS server is down")
        kid = jwt.get_unverified_header(token).get("kid")
        key = self.issuer.public_key_for(kid) if kid else None
        if key is None:
            raise jwt.PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')
        return SimpleNamespace(key=key, key_id=kid)


def stub_settings(issuer: StubIssuer, *, backend_id: str = "dept_a") -> dict[str, object]:
    return {
        "DEBUG": True,
        "ENTRA_SSO_ONLY": False,
        "ENTRA_STUB_ISSUER_ENABLED": True,
        "ENTRA_STUB_TENANT_ID": STUB_TENANT_ID,
        "AAD_TENANT_ID": issuer.tenant,
        "AAD_ISSUER": ISSUER_TEMPLATE.format(tenant=issuer.tenant),
        "AAD_AUDIENCE": issuer.audience,
        "AAD_JWKS_URL": f"http://127.0.0.1:8765/{issuer.tenant}/discovery/v2.0/keys",
        "ENTRA_API_ACCESS_TOKENS_ENABLED": True,
        "ENTRA_API_AUDIENCES": [f"api://{issuer.audience}", issuer.audience],
        "ENTRA_BIND_BY_USERNAME": True,
        "ENTRA_BIND_ALLOWED_DOMAINS": [UPN_DOMAIN],
        "BACKEND_ID": backend_id,
        "ROUTING_SYNC_AUDIENCE": f"api://labmango-{backend_id}",
        "ROUTING_SYNC_ENTRA_TENANT_IDS": [issuer.tenant],
        "ROUTING_SYNC_JWKS_URL": f"http://127.0.0.1:8765/{issuer.tenant}/discovery/v2.0/keys",
    }


@contextmanager
def stub_entra_environment(issuer: StubIssuer, *, unreachable: bool = False, **overrides: object) -> Iterator[None]:
    client = StubJWKClient(issuer, unreachable=unreachable)
    with ExitStack() as stack:
        stack.enter_context(override_settings(**{**stub_settings(issuer), **overrides}))
        for target in JWKS_LOOKUPS:
            stack.enter_context(patch(target, return_value=client))
        yield
