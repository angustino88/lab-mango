"""Stub Entra ID issuer for local development: signing keys, a loopback JWKS server, and tokens.

The backend validates these tokens with its unchanged production validators; only the signing-key URL
differs. Typical use (from the repository root):

    python -m tools.stubs entra init            # create a key, print the .env block
    python -m tools.stubs entra serve           # keep running: serves the JWKS on 127.0.0.1:8765
    python -m tools.stubs entra login alice     # POST /api/aad-login, store alice's Lab Mango token
    python -m tools.stubs entra call alice GET /api/bench-bookings
    python -m tools.stubs entra app-token       # Routing.Sync.Read application token for the router
    python -m tools.stubs entra id-token alice --expired     # negative tokens: see --help for fault flags

Keys and sessions live in ``$LABMANGO_STUB_HOME`` (default ``~/.labmango-stub``) with mode 0600. Never point
a real deployment at this issuer; the backend's system checks refuse it outside local DEBUG.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tools.stubs.common import (
    DEFAULT_AUDIENCE,
    DEFAULT_BASE_URL,
    DEFAULT_JWKS_PORT,
    STUB_TENANT_ID,
    UPN_DOMAIN,
    HttpResult,
    Persona,
    PersonaManifest,
    dump,
    http,
    load_personas,
    read_json,
    state_home,
    write_private,
)

ISSUER_TEMPLATE = "https://login.microsoftonline.com/{tenant}/v2.0"
AUDIT_SCOPE = "LabMango.Audit"
SYNC_ROLE = "Routing.Sync.Read"
TOKEN_LIFETIME_S = 3600


@dataclass(frozen=True, slots=True)
class Faults:
    """Ways to make a token invalid on purpose. Each maps to one validator rule."""

    expired: bool = False
    not_yet_valid: bool = False
    stale_iat: bool = False  # older than ENTRA_LOGIN_MAX_TOKEN_AGE (10 min)
    audience: str | None = None
    tenant: str | None = None
    no_role: bool = False
    with_scp: bool = False
    unknown_kid: bool = False
    hs256: bool = False
    guest: bool = False


def nonce_for_secret(nonce_secret: str) -> str:
    """Same as core.users.features.auth.aad_login.service.nonce_for_secret."""
    digest = hashlib.sha256(nonce_secret.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class StubIssuer:
    """RSA signing keys plus token minting. The first key signs; every key is published in the JWKS."""

    keys: list[rsa.RSAPrivateKey]
    tenant: str = STUB_TENANT_ID
    audience: str = DEFAULT_AUDIENCE
    manifest: PersonaManifest = field(default_factory=load_personas)

    @classmethod
    def generate(cls, **kwargs: Any) -> StubIssuer:
        return cls(keys=[_new_key()], **kwargs)

    # Keys ------------------------------------------------------------------------------------------------

    @staticmethod
    def kid(key: rsa.RSAPrivateKey) -> str:
        der = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return hashlib.sha256(der).hexdigest()[:16]

    def jwks(self) -> dict[str, Any]:
        entries = []
        for key in self.keys:
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
            entries.append({**jwk, "kid": self.kid(key), "use": "sig", "alg": "RS256"})
        return {"keys": entries}

    def public_key_for(self, kid: str) -> rsa.RSAPublicKey | None:
        for key in self.keys:
            if self.kid(key) == kid:
                return key.public_key()
        return None

    @property
    def issuer(self) -> str:
        return ISSUER_TEMPLATE.format(tenant=self.tenant)

    # Tokens ----------------------------------------------------------------------------------------------

    def sign(self, claims: dict[str, Any], faults: Faults = Faults()) -> str:
        if faults.hs256:
            return jwt.encode(claims, secrets.token_bytes(32), algorithm="HS256")
        if faults.unknown_kid:
            return jwt.encode(claims, _new_key(), algorithm="RS256", headers={"kid": "unknown-stub-kid"})
        key = self.keys[0]
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": self.kid(key), "typ": "JWT"})

    def _base(self, *, audience: str, faults: Faults) -> dict[str, Any]:
        now = int(time.time())
        issued = now - 15 * 60 if faults.stale_iat else now - 5
        not_before = now + 600 if faults.not_yet_valid else issued
        expires = now - 600 if faults.expired else now + TOKEN_LIFETIME_S
        tenant = faults.tenant or self.tenant
        return {
            "iss": ISSUER_TEMPLATE.format(tenant=tenant),
            "aud": faults.audience or audience,
            "tid": tenant,
            "iat": issued,
            "nbf": not_before,
            "exp": expires,
            "ver": "2.0",
        }

    def user_claims(self, persona: Persona, *, faults: Faults) -> dict[str, Any]:
        object_id = str(self.manifest.object_id(persona, tenant=self.tenant))
        upn = persona.upn
        claims: dict[str, Any] = {"oid": object_id, "name": persona.name, "preferred_username": upn}
        if faults.guest:
            claims["preferred_username"] = upn.replace("@", "_") + f"#EXT#@{UPN_DOMAIN}"
            claims["acct"] = 1
        # Entra's sub is pairwise per application; derive it from oid and audience, as Entra does in effect.
        claims["sub"] = base64.urlsafe_b64encode(
            hashlib.sha256(f"{object_id}:{self.audience}".encode()).digest()
        ).decode()[:43]
        return claims

    def id_token(self, persona: Persona, *, faults: Faults = Faults()) -> tuple[str, str]:
        """An ID token for ``POST /api/aad-login`` and the nonce secret that goes with it."""
        nonce_secret = secrets.token_urlsafe(32)
        claims = {
            **self._base(audience=self.audience, faults=faults),
            **self.user_claims(persona, faults=faults),
            "nonce": nonce_for_secret(nonce_secret),
        }
        return self.sign(claims, faults), nonce_secret

    def access_token(self, persona: Persona, *, scope: str = AUDIT_SCOPE, faults: Faults = Faults()) -> str:
        """A delegated access token (``scp``) for views that accept EntraAccessTokenAuthentication."""
        claims = {
            **self._base(audience=f"api://{self.audience}", faults=faults),
            **self.user_claims(persona, faults=faults),
            "scp": scope,
            "idtyp": "user",
        }
        return self.sign(claims, faults)

    def app_token(
        self, *, audience: str = "api://labmango-dept_a", role: str = SYNC_ROLE, faults: Faults = Faults()
    ) -> str:
        """An application-only token (client credentials) for the routing sync API."""
        claims: dict[str, Any] = {
            **self._base(audience=audience, faults=faults),
            "oid": str(uuid.uuid5(self.manifest.namespace, "stub-router")),
            "sub": str(uuid.uuid5(self.manifest.namespace, "stub-router")),
            "azp": str(uuid.uuid5(self.manifest.namespace, "stub-router-app")),
            "idtyp": "app",
            "roles": [] if faults.no_role else [role],
        }
        if faults.with_scp:
            claims["scp"] = AUDIT_SCOPE
        return self.sign(claims, faults)

    # Persistence -----------------------------------------------------------------------------------------

    def save(self) -> None:
        pems = [
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode("ascii")
            for key in self.keys
        ]
        write_private(_issuer_file(), {"tenant": self.tenant, "audience": self.audience, "keys": pems})

    @classmethod
    def load(cls) -> StubIssuer:
        state = read_json(_issuer_file())
        if state is None:
            raise SystemExit("No stub issuer yet; run: python -m tools.stubs entra init")
        keys = [serialization.load_pem_private_key(pem.encode("ascii"), password=None) for pem in state["keys"]]
        return cls(keys=keys, tenant=state["tenant"], audience=state["audience"])  # type: ignore[arg-type]


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _issuer_file():
    return state_home() / "entra" / "issuer.json"


def jwks_path(tenant: str) -> str:
    return f"/{tenant}/discovery/v2.0/keys"


def env_block(issuer: StubIssuer, *, port: int = DEFAULT_JWKS_PORT, backend_id: str = "dept_a") -> str:
    return "\n".join(
        (
            "# Stub Entra issuer (tools/stubs); local development only",
            "ENTRA_STUB_ISSUER_ENABLED=True",
            f"AAD_TENANT_ID={issuer.tenant}",
            f"AAD_AUDIENCE={issuer.audience}",
            f"AAD_JWKS_URL=http://127.0.0.1:{port}{jwks_path(issuer.tenant)}",
            f"ENTRA_API_AUDIENCES=api://{issuer.audience},{issuer.audience}",
            f"ENTRA_BIND_ALLOWED_DOMAINS={UPN_DOMAIN}",
            f"BACKEND_ID={backend_id}",
            f"ROUTING_SYNC_AUDIENCE=api://labmango-{backend_id}",
            "REFRESH_TOKEN_COOKIE_SECURE=False",
            "# scenarios log in many times a minute; the default is 10/min",
            "THROTTLE_AUTH_LOGIN=600/min",
        )
    )


# Sessions: a persona's Lab Mango access token from /api/aad-login ---------------------------------------


def _session_file(key: str):
    return state_home() / "sessions" / f"{key}.json"


def login(
    issuer: StubIssuer, persona: Persona, *, base_url: str = DEFAULT_BASE_URL, faults: Faults = Faults()
) -> HttpResult:
    # Same as the browser: fetch the CSRF cookie and token first (CookieCSRFPermission on /api/aad-login).
    csrf = http(base_url, "GET", "/api/csrf-token")
    token = (csrf.data or {}).get("csrf_token") if csrf.ok else None
    if not token or "csrftoken" not in csrf.cookies:
        return csrf
    id_token, nonce_secret = issuer.id_token(persona, faults=faults)
    result = http(
        base_url,
        "POST",
        "/api/aad-login",
        body=json.dumps({"id_token": id_token, "nonce_secret": nonce_secret}).encode(),
        headers={"X-CSRFToken": token, "Cookie": f"csrftoken={csrf.cookies['csrftoken']}"},
    )
    if result.ok and isinstance(result.data, dict) and result.data.get("access"):
        write_private(
            _session_file(persona.key),
            {"base_url": base_url, "username": persona.username, "access": result.data["access"]},
        )
    return result


def call_as(
    persona: Persona,
    method: str,
    path: str,
    *,
    body: Any = None,
    base_url: str | None = None,
    issuer: StubIssuer | None = None,
) -> HttpResult:
    """Send an API request as ``persona``; log in first when there is no session or it has expired."""
    session = read_json(_session_file(persona.key))
    base = base_url or (session or {}).get("base_url") or DEFAULT_BASE_URL
    raw = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    for attempt in range(2):
        if session is None or attempt == 1:
            result = login(issuer or StubIssuer.load(), persona, base_url=base)
            if not result.ok:
                return result
            session = read_json(_session_file(persona.key))
        result = http(base, method, path, body=raw, headers={"Authorization": f"Bearer {session['access']}"})
        if result.status != 401:
            return result
    return result


# JWKS server -----------------------------------------------------------------------------------------------


def serve(issuer: StubIssuer, *, port: int = DEFAULT_JWKS_PORT) -> None:
    body = json.dumps(issuer.jwks()).encode()
    paths = {jwks_path(issuer.tenant), "/keys"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path.split("?", 1)[0] not in paths:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            sys.stderr.write(f"jwks: {self.address_string()} {format % args}\n")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # loopback only, by design
    print(f"Serving stub JWKS on http://127.0.0.1:{port}{jwks_path(issuer.tenant)} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# CLI -------------------------------------------------------------------------------------------------------


def _add_faults(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("fault flags (produce an invalid token on purpose)")
    group.add_argument("--expired", action="store_true")
    group.add_argument("--not-yet-valid", action="store_true")
    group.add_argument("--stale-iat", action="store_true", help="issued 15 min ago (login max age is 10)")
    group.add_argument("--aud", help="wrong audience")
    group.add_argument("--tenant", help="wrong tenant (iss and tid)")
    group.add_argument("--no-role", action="store_true", help="app token without the role")
    group.add_argument("--with-scp", action="store_true", help="app token that also carries scp")
    group.add_argument("--unknown-kid", action="store_true", help="signed by a key not in the JWKS")
    group.add_argument("--hs256", action="store_true", help="HS256 instead of RS256")
    group.add_argument("--guest", action="store_true", help="#EXT# guest UPN")


def _faults(args: argparse.Namespace) -> Faults:
    return Faults(
        expired=args.expired,
        not_yet_valid=args.not_yet_valid,
        stale_iat=args.stale_iat,
        audience=args.aud,
        tenant=args.tenant,
        no_role=args.no_role,
        with_scp=args.with_scp,
        unknown_kid=args.unknown_kid,
        hs256=args.hs256,
        guest=args.guest,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.stubs entra", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create the signing key (once) and print the .env block")
    init.add_argument("--audience", default=DEFAULT_AUDIENCE)
    init.add_argument("--port", type=int, default=DEFAULT_JWKS_PORT)
    init.add_argument("--backend-id", default="dept_a")
    init.add_argument("--force", action="store_true", help="replace an existing key")

    env = commands.add_parser("env", help="print the .env block again")
    env.add_argument("--port", type=int, default=DEFAULT_JWKS_PORT)
    env.add_argument("--backend-id", default="dept_a")

    serve_parser = commands.add_parser("serve", help="serve the JWKS on 127.0.0.1 (stop it to simulate an outage)")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_JWKS_PORT)

    rotate = commands.add_parser("rotate", help="new signing key; restart serve afterwards")
    rotate.add_argument("--keep-old", action="store_true", help="keep publishing the old key (rotation overlap)")

    for name, help_text in (
        ("id-token", "print an ID token and its nonce secret for POST /api/aad-login"),
        ("access-token", "print a delegated access token (scp) for the audit-tool views"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("persona")
        if name == "access-token":
            sub.add_argument("--scope", default=AUDIT_SCOPE)
        _add_faults(sub)

    app = commands.add_parser("app-token", help="print a Routing.Sync.Read application token")
    app.add_argument("--audience", default="api://labmango-dept_a")
    app.add_argument("--role", default=SYNC_ROLE)
    _add_faults(app)

    login_parser = commands.add_parser("login", help="log a persona in and store its Lab Mango access token")
    login_parser.add_argument("persona")
    login_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    _add_faults(login_parser)

    call = commands.add_parser("call", help="send an API request as a persona (logs in when needed)")
    call.add_argument("persona")
    call.add_argument("method")
    call.add_argument("path")
    call.add_argument("--json", default=None, help="raw JSON body")
    call.add_argument("--base-url", default=None)

    commands.add_parser("personas", help="list personas with their object IDs and routing keys")

    args = parser.parse_args(argv)

    if args.command == "init":
        existing = read_json(_issuer_file())
        if existing is not None and not args.force:
            issuer = StubIssuer.load()
            print(f"# Using the existing key in {_issuer_file()} (--force replaces it)", file=sys.stderr)
        else:
            issuer = StubIssuer.generate(audience=args.audience)
            issuer.save()
            print(f"# New stub signing key written to {_issuer_file()}", file=sys.stderr)
        print(env_block(issuer, port=args.port, backend_id=args.backend_id))
        return 0
    if args.command == "personas":
        manifest = load_personas()
        for persona in manifest.personas.values():
            print(
                f"{persona.key:<6} {persona.username:<11} role={persona.labs_role or '-':<5} "
                f"backend={persona.backend} bound={persona.bound} active={persona.active} "
                f"oid={manifest.object_id(persona)} key={manifest.user_key(persona)}"
            )
        return 0

    issuer = StubIssuer.load()
    if args.command == "env":
        print(env_block(issuer, port=args.port, backend_id=args.backend_id))
    elif args.command == "serve":
        serve(issuer, port=args.port)
    elif args.command == "rotate":
        issuer.keys = [_new_key(), *(issuer.keys if args.keep_old else [])]
        issuer.save()
        print(f"New signing key {issuer.kid(issuer.keys[0])}; published keys: {len(issuer.keys)}. Restart serve.")
    elif args.command == "id-token":
        token, nonce_secret = issuer.id_token(issuer.manifest.get(args.persona), faults=_faults(args))
        print(json.dumps({"id_token": token, "nonce_secret": nonce_secret}, indent=2))
    elif args.command == "access-token":
        print(issuer.access_token(issuer.manifest.get(args.persona), scope=args.scope, faults=_faults(args)))
    elif args.command == "app-token":
        print(issuer.app_token(audience=args.audience, role=args.role, faults=_faults(args)))
    elif args.command == "login":
        result = login(issuer, issuer.manifest.get(args.persona), base_url=args.base_url, faults=_faults(args))
        if result.ok:
            print(
                f"{result.status} logged in as {result.data.get('username')}; session in {_session_file(args.persona)}"
            )
        else:
            print(dump(result))
        return 0 if result.ok else 1
    elif args.command == "call":
        body = args.json.encode() if args.json is not None else None
        result = call_as(issuer.manifest.get(args.persona), args.method, args.path, body=body, base_url=args.base_url)
        print(dump(result))
        return 0 if result.ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
