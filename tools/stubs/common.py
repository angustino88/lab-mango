"""Shared helpers for the stubs: state directory, persona manifest, HTTP. Standard library only."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

# Must equal settings.ENTRA_STUB_TENANT_ID. A version-0 UUID: Entra never issues it to a real tenant.
STUB_TENANT_ID = "00000000-0000-0000-0000-0000000057ab"
UPN_DOMAIN = "stub.labmango.test"  # .test is reserved (RFC 2606)
USERNAME_PREFIX = "stub."  # Must equal core.users.public.STUB_USERNAME_PREFIX.
DEFAULT_AUDIENCE = "labmango-local"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_JWKS_PORT = 8765
PACKAGE_DIR = Path(__file__).resolve().parent
PERSONAS_FILE = PACKAGE_DIR / "personas.json"
LAB_FILE = PACKAGE_DIR / "lab.json"


def state_home() -> Path:
    """Where keys, sessions and agent profiles live: ``$LABMANGO_STUB_HOME`` or ``~/.labmango-stub``."""
    home = Path(os.environ.get("LABMANGO_STUB_HOME") or Path.home() / ".labmango-stub")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    return home


def write_private(path: Path, data: Any) -> None:
    """Write JSON readable by the owner only; these files hold private keys and tokens."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(data, handle, indent=2)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


# Personas ------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Persona:
    key: str
    name: str
    backend: str
    labs_role: str
    bound: bool
    active: bool

    @property
    def username(self) -> str:
        return f"{USERNAME_PREFIX}{self.key}"

    @property
    def upn(self) -> str:
        return f"{self.username}@{UPN_DOMAIN}"

    @property
    def email(self) -> str:
        return self.upn


@dataclass(frozen=True, slots=True)
class PersonaManifest:
    namespace: uuid.UUID
    personas: dict[str, Persona]

    def get(self, ref: str) -> Persona:
        key = ref.removeprefix("@").removeprefix(USERNAME_PREFIX)
        try:
            return self.personas[key]
        except KeyError:
            raise SystemExit(f"Unknown persona {ref!r}; known: {', '.join(sorted(self.personas))}") from None

    def object_id(self, persona: Persona, *, tenant: str = STUB_TENANT_ID, generation: int | None = None) -> uuid.UUID:
        """Deterministic Entra object ID: the same persona gets the same routing key after a database reset."""
        if generation is None:
            generation = generations().get(persona.key, 0)
        return uuid.uuid5(self.namespace, f"{str(uuid.UUID(tenant)).lower()}:{persona.key}:{generation}")

    def user_key(self, persona: Persona, *, tenant: str = STUB_TENANT_ID, generation: int | None = None) -> str:
        object_id = self.object_id(persona, tenant=tenant, generation=generation)
        return f"entra:{str(uuid.UUID(tenant)).lower()}:{str(object_id).lower()}"


def load_personas(path: Path = PERSONAS_FILE) -> PersonaManifest:
    raw = json.loads(path.read_text())
    personas = {}
    for item in raw["personas"]:
        persona = Persona(
            key=item["key"],
            name=item.get("name", item["key"].title()),
            backend=item.get("backend", "dept_a"),
            labs_role=item.get("labs_role", ""),
            bound=bool(item.get("bound", True)),
            active=bool(item.get("active", True)),
        )
        if persona.labs_role not in {"", "user", "coord", "admin"}:
            raise ValueError(f"persona {persona.key}: unknown labs_role {persona.labs_role!r}")
        personas[persona.key] = persona
    return PersonaManifest(namespace=uuid.UUID(raw["namespace"]), personas=personas)


def generations() -> dict[str, int]:
    """Per-persona binding generation; ``identities replace`` bumps it, so issuer and backend agree."""
    return read_json(state_home() / "generations.json", {})


def set_generation(key: str, generation: int) -> None:
    current = generations()
    current[key] = generation
    write_private(state_home() / "generations.json", current)


# HTTP ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def data(self) -> Any:
        return self.body.get("data") if isinstance(self.body, dict) else None


def http(
    base_url: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> HttpResult:
    """One HTTP request; JSON bodies are decoded, anything else is returned as text. Never raises on 4xx/5xx."""
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body if method.upper() != "GET" else None,
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status, _decode(response.read()), *_headers(response.headers))
    except urllib.error.HTTPError as error:
        return HttpResult(error.code, _decode(error.read()), *_headers(error.headers))


def _headers(message: Any) -> tuple[dict[str, str], dict[str, str]]:
    cookies: dict[str, str] = {}
    for raw in message.get_all("Set-Cookie") or []:
        jar: SimpleCookie = SimpleCookie()
        jar.load(raw)
        cookies.update({name: morsel.value for name, morsel in jar.items()})
    return dict(message.items()), cookies


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def dump(result: HttpResult) -> str:
    return f"{result.status} {json.dumps(result.body, indent=2, default=str)}"
