"""Stub agent: the signed ``/agent/...`` device API, booking actions, and the operator API.

Device commands sign each request with the profile's Ed25519 key, as a real agent does. Operator commands run
as a stub persona (default ``carol``, a coordinator) through the stub Entra login. The agent never creates
or approves bookings (ADR 004); book as a user with ``python -m tools.stubs scenario book``.

    # One step: grant + enroll for the stub computer pc-1 (from ``lab seed``), as carol:
    python -m tools.stubs agent provision --equipment pc-1 --profile pc-1
    # Device API (signed):
    python -m tools.stubs agent --profile pc-1 heartbeat
    python -m tools.stubs agent --profile pc-1 activity --status active --remote-user @alice
    python -m tools.stubs agent --profile pc-1 session-log --remote-user @alice --minutes 45
    python -m tools.stubs agent --profile pc-1 booking validate --code <code>
    python -m tools.stubs agent --profile pc-1 booking check-in --code <code>
    python -m tools.stubs agent --profile pc-1 booking extend --code <code> --by 30m
    python -m tools.stubs agent --profile pc-1 booking complete --code <code>
    python -m tools.stubs agent --profile pc-1 session --as @alice --code <code> --extend-by 30m
    # Faults (each must be refused with 401): --skew 900 / --replay / --tamper-body / --wrong-key / --path-mismatch
    # Operator API (as a persona):
    python -m tools.stubs agent agents list
    python -m tools.stubs agent grant create --equipment pc-2
    python -m tools.stubs agent revoke --agent 7

Legacy use is unchanged: ``python tools/stub_agent.py enroll --base-url ... --agent-uid ... --grant ...`` and
``--key-file`` (default ``~/.labmango-stub-agent.json``). Profiles live in ``$LABMANGO_STUB_HOME/agents``.
Key files hold private keys: keep them outside the repository and never use them for a real device.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.stubs.common import (
    DEFAULT_BASE_URL,
    USERNAME_PREFIX,
    HttpResult,
    dump,
    http,
    read_json,
    state_home,
    write_private,
)

# Must match core/agents/application.py (ENROLLMENT_CONTEXT, REQUEST_SIGNATURE_CONTEXT, agent_request_message).
ENROLLMENT_CONTEXT = b"labmango-enroll-v1"
REQUEST_SIGNATURE_CONTEXT = b"labmango-agent-request-v1"
DEFAULT_KEY_FILE = Path.home() / ".labmango-stub-agent.json"
SIGNING_FAULTS = ("skew", "replay", "tamper_body", "wrong_key", "path_mismatch")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def profile_path(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise SystemExit("Profile names use letters, digits, '.', '_' and '-'.")
    return state_home() / "agents" / f"{name}.json"


def expand_user(value: str | None) -> str | None:
    """``@alice`` -> ``stub.alice``, so agent reports name injected persona users."""
    if value is not None and value.startswith("@"):
        return f"{USERNAME_PREFIX}{value[1:]}"
    return value


@dataclass(frozen=True, slots=True)
class SigningFaults:
    skew: int = 0  # seconds added to the timestamp
    replay: bool = False  # reuse the previous request's nonce
    tamper_body: bool = False  # sign one body, send another
    wrong_key: bool = False  # sign with a key that is not enrolled
    path_mismatch: bool = False  # sign a different path


@dataclass
class StubAgent:
    """An enrolled stub agent: identity, key, and the state a real device keeps between requests."""

    key_file: Path
    base_url: str
    backend_id: str
    agent_uid: str
    key: Ed25519PrivateKey
    equipment_uid: str | None = None
    last_nonce: str | None = None
    last_event_key: str | None = None
    _pending_nonce: str | None = None

    @classmethod
    def load(cls, key_file: Path) -> StubAgent:
        state = read_json(key_file)
        if state is None:
            raise SystemExit(f"No stub agent at {key_file}; enroll or provision first.")
        return cls(
            key_file=key_file,
            base_url=state["base_url"],
            backend_id=state["backend_id"],
            agent_uid=state["agent_uid"],
            key=Ed25519PrivateKey.from_private_bytes(b64url_decode(state["private_key"])),
            equipment_uid=state.get("equipment_uid"),
            last_nonce=state.get("last_nonce"),
            last_event_key=state.get("last_event_key"),
        )

    def save(self) -> None:
        raw = self.key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        write_private(
            self.key_file,
            {
                "base_url": self.base_url,
                "backend_id": self.backend_id,
                "agent_uid": self.agent_uid,
                "equipment_uid": self.equipment_uid,
                "private_key": b64url(raw),
                "last_nonce": self.last_nonce,
                "last_event_key": self.last_event_key,
            },
        )

    def signed_headers(
        self, method: str, path: str, body: bytes, faults: SigningFaults = SigningFaults()
    ) -> dict[str, str]:
        timestamp = str(int(time.time()) + faults.skew)
        nonce = self.last_nonce if faults.replay and self.last_nonce else b64url(secrets.token_bytes(16))
        signed_path = path + "x" if faults.path_mismatch else path
        signed_body = body + b" " if faults.tamper_body else body
        message = b"\0".join(
            (
                REQUEST_SIGNATURE_CONTEXT,
                self.backend_id.encode("ascii"),
                self.agent_uid.encode("ascii"),
                method.upper().encode("ascii"),
                signed_path.encode("utf-8"),
                timestamp.encode("ascii"),
                nonce.encode("ascii"),
                hashlib.sha256(signed_body).hexdigest().encode("ascii"),
            )
        )
        key = Ed25519PrivateKey.generate() if faults.wrong_key else self.key
        self._pending_nonce = nonce
        return {
            "X-Agent-Id": self.agent_uid,
            "X-Agent-Timestamp": timestamp,
            "X-Agent-Nonce": nonce,
            "X-Agent-Signature": b64url(key.sign(message)),
        }

    def send(self, method: str, path: str, body: bytes, faults: SigningFaults = SigningFaults()) -> HttpResult:
        headers = self.signed_headers(method, path, body, faults)
        result = http(self.base_url, method.upper(), path, body=body, headers=headers)
        if result.ok:
            self.last_nonce = self._pending_nonce  # only an accepted nonce is worth replaying
        if self.key_file.exists():
            self.save()  # remember the nonce, for --replay
        return result

    def send_json(self, method: str, path: str, payload: dict[str, Any], faults: SigningFaults = SigningFaults()):
        return self.send(method, path, json.dumps(payload, separators=(",", ":")).encode(), faults)

    # Device API --------------------------------------------------------------------------------------------

    def heartbeat(self, faults: SigningFaults = SigningFaults()) -> HttpResult:
        return self.send("POST", "/agent/heartbeat", b"{}", faults)

    def activity(self, faults: SigningFaults = SigningFaults(), **fields: Any) -> HttpResult:
        payload = {name: value for name, value in fields.items() if value is not None}
        if "remote_user" in payload:
            payload["remote_user"] = expand_user(payload["remote_user"])
        return self.send_json("PATCH", "/agent/equipment/activity", payload, faults)

    def session_log(
        self,
        *,
        remote_user: str,
        minutes: float,
        booking_code: str | None = None,
        event_key: str | None = None,
        remote_ip: str | None = "127.0.0.1",
        faults: SigningFaults = SigningFaults(),
    ) -> HttpResult:
        logout = datetime.now(UTC).replace(microsecond=0)
        login = logout - timedelta(minutes=minutes)
        event_key = event_key or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "event_key": event_key,
            "login_at": login.isoformat(),
            "logout_at": logout.isoformat(),
            "active_duration_seconds": minutes * 60,
            "remote_user": expand_user(remote_user),
            "remote_ip": remote_ip,
            "remote_host": "stub-host",
            "agent_version": "stub-1",
        }
        if booking_code:
            payload["booking_code"] = booking_code
        result = self.send_json("POST", "/agent/session-logs", payload, faults)
        self.last_event_key = event_key
        if self.key_file.exists():
            self.save()
        return result

    def booking(self, action: str, code: str, faults: SigningFaults = SigningFaults(), **extra: Any) -> HttpResult:
        if action not in {"validate", "check-in", "complete", "extend"}:
            raise ValueError(action)
        return self.send_json("POST", f"/agent/bookings/actions/{action}", {"booking_code": code, **extra}, faults)

    def extend_by(self, code: str, delta: timedelta, faults: SigningFaults = SigningFaults()) -> HttpResult:
        """Extend from the booking's current end (read with validate) by ``delta``."""
        current = self.booking("validate", code)
        ends_at = (current.data or {}).get("ends_at")
        if not current.ok or not ends_at:
            return current
        new_end = datetime.fromisoformat(ends_at.replace("Z", "+00:00")) + delta
        return self.booking("extend", code, faults, ends_at=new_end.isoformat())


# Enrollment --------------------------------------------------------------------------------------------------


def enroll(
    *, base_url: str, agent_uid: str, grant: str, key_file: Path, equipment_uid: str | None = None
) -> tuple[HttpResult, StubAgent | None]:
    info = http(base_url, "GET", "/agent/info")
    if not info.ok:
        return info, None
    backend_id = info.data["backend_key"]
    key = Ed25519PrivateKey.generate()
    der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    proof = key.sign(
        b"\0".join(
            (
                ENROLLMENT_CONTEXT,
                backend_id.encode("ascii"),
                agent_uid.encode("ascii"),
                hashlib.sha256(grant.encode()).hexdigest().encode("ascii"),
                der,
            )
        )
    )
    payload = {
        "grant": grant,
        "public_key": b64url(der),
        "key_storage": "software",
        "fingerprint": "stub-agent",
        "agent_version": "stub-1",
        "proof": b64url(proof),
    }
    result = http(base_url, "POST", "/agent/enrollments", body=json.dumps(payload).encode())
    if not result.ok:
        return result, None
    agent = StubAgent(
        key_file=key_file,
        base_url=base_url,
        backend_id=backend_id,
        agent_uid=agent_uid,
        key=key,
        equipment_uid=equipment_uid,
    )
    agent.save()
    return result, agent


# Operator API (as a persona) -----------------------------------------------------------------------------------


def _operator(persona_ref: str, method: str, path: str, body: Any = None, base_url: str | None = None) -> HttpResult:
    from tools.stubs.common import load_personas
    from tools.stubs.entra import call_as

    return call_as(load_personas().get(persona_ref), method, path, body=body, base_url=base_url)


def resolve_equipment_uid(value: str) -> str:
    """A UUID is used as is; a stub lab key (``pc-1``) is looked up with ``lab list``."""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        pass
    from tools.stubs.identities import setup_django
    from tools.stubs.lab import rows

    setup_django()
    for row in rows():
        if row.kind == "computing" and row.key == value and row.uid:
            return row.uid
    raise SystemExit(f"Unknown stub computer {value!r}; run: python -m tools.stubs lab seed")


def provision(
    *, persona: str, equipment: str, profile: str, base_url: str = DEFAULT_BASE_URL, ttl: int = 15
) -> tuple[HttpResult, StubAgent | None]:
    """Grant (as ``persona``) and enroll a stub agent for ``equipment``; stores the agent as ``profile``."""
    equipment_uid = resolve_equipment_uid(equipment)
    granted = _operator(
        persona, "POST", "/api/agents", {"equipment_uid": equipment_uid, "ttl_minutes": ttl}, base_url=base_url
    )
    if not granted.ok:
        return granted, None
    return enroll(
        base_url=base_url,
        agent_uid=granted.data["agent_uid"],
        grant=granted.data["grant"],
        key_file=profile_path(profile),
        equipment_uid=equipment_uid,
    )


def parse_duration(text: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([smh])", text)
    if not match:
        raise argparse.ArgumentTypeError("use e.g. 90s, 30m, 2h")
    value, unit = int(match.group(1)), match.group(2)
    return timedelta(seconds=value * {"s": 1, "m": 60, "h": 3600}[unit])


def run_session(
    agent: StubAgent,
    *,
    user: str,
    code: str,
    minutes: float = 1,
    extend_by: timedelta | None = None,
    heartbeats: int = 1,
    complete: bool = True,
    log: Any = print,
) -> bool:
    """A workstation login end to end. Returns True when every step succeeded."""
    steps: list[tuple[str, Any]] = [
        ("validate", lambda: agent.booking("validate", code)),
        ("check-in", lambda: agent.booking("check-in", code)),
        ("activity active", lambda: agent.activity(status="active", remote_user=user, booking_code=code)),
        *[("heartbeat", agent.heartbeat) for _ in range(heartbeats)],
    ]
    if extend_by is not None:
        steps.append(("extend", lambda: agent.extend_by(code, extend_by)))
    steps.append(("session-log", lambda: agent.session_log(remote_user=user, minutes=minutes, booking_code=code)))
    if complete:
        steps.append(("complete", lambda: agent.booking("complete", code)))
    steps.append(("activity free", lambda: agent.activity(status="free", remote_user="", booking_code="")))
    success = True
    for name, step in steps:
        result = step()
        flag = _flag(result)
        log(f"{'ok ' if result.ok and flag is not False else 'FAIL'} {name:<16} {result.status} {flag_text(result)}")
        success &= result.ok and flag is not False
    return success


def _flag(result: HttpResult) -> bool | None:
    data = result.data if isinstance(result.data, dict) else {}
    for name in ("is_eligible", "is_checked_in", "is_extended", "is_completed"):
        if name in data:
            return bool(data[name])
    return None


def flag_text(result: HttpResult) -> str:
    data = result.data if isinstance(result.data, dict) else None
    if data is None:
        return json.dumps(result.body, default=str)[:200]
    keys = ("is_eligible", "is_checked_in", "is_extended", "is_completed", "status", "ends_at", "booked_for")
    return " ".join(f"{key}={data[key]}" for key in keys if key in data)


# CLI ------------------------------------------------------------------------------------------------------------


def _add_signing_faults(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("signing faults (the backend must answer 401)")
    group.add_argument("--skew", type=int, default=0, help="seconds added to the timestamp, e.g. 900")
    group.add_argument("--replay", action="store_true", help="reuse the previous nonce")
    group.add_argument("--tamper-body", action="store_true")
    group.add_argument("--wrong-key", action="store_true")
    group.add_argument("--path-mismatch", action="store_true")


def _signing_faults(args: argparse.Namespace) -> SigningFaults:
    return SigningFaults(
        skew=getattr(args, "skew", 0),
        replay=getattr(args, "replay", False),
        tamper_body=getattr(args, "tamper_body", False),
        wrong_key=getattr(args, "wrong_key", False),
        path_mismatch=getattr(args, "path_mismatch", False),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.stubs agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--key-file", type=Path, default=None, help=f"legacy key file (default {DEFAULT_KEY_FILE})")
    target.add_argument("--profile", default=None, help="named profile in $LABMANGO_STUB_HOME/agents")
    parser.add_argument("--as", dest="persona", default="carol", help="persona for operator commands")
    parser.add_argument("--base-url", dest="global_base_url", default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    enroll_parser = commands.add_parser("enroll", help="enroll with a one-time grant")
    enroll_parser.add_argument("--base-url", required=True)
    enroll_parser.add_argument("--agent-uid", required=True)
    enroll_parser.add_argument("--grant", required=True)
    enroll_parser.add_argument("--equipment-uid", default=None)

    prov = commands.add_parser("provision", help="grant as a persona, then enroll, in one step")
    prov.add_argument("--equipment", required=True, help="stub lab key (pc-1) or equipment UID")
    prov.add_argument("--ttl", type=int, default=15)

    commands.add_parser("profiles", help="list stored agent profiles")
    commands.add_parser("info", help="GET /agent/info (unsigned)")

    heartbeat = commands.add_parser("heartbeat", help="POST /agent/heartbeat")
    heartbeat.add_argument("--every", type=float, default=0, help="seconds between heartbeats (loop)")
    heartbeat.add_argument("--count", type=int, default=1)
    _add_signing_faults(heartbeat)

    activity = commands.add_parser("activity", help="PATCH /agent/equipment/activity")
    activity.add_argument("--status", choices=["offline", "free", "active", "inactive", "maintaining"])
    for name in ("remote-user", "remote-user-display-name", "remote-computer", "remote-ip", "booking-code"):
        activity.add_argument(f"--{name}")
    _add_signing_faults(activity)

    session_log = commands.add_parser("session-log", help="POST /agent/session-logs")
    session_log.add_argument("--remote-user", required=True, help="username or @persona")
    session_log.add_argument("--minutes", type=float, default=30)
    session_log.add_argument("--booking-code", default=None)
    replay_group = session_log.add_mutually_exclusive_group()
    replay_group.add_argument("--event-key", default=None)
    replay_group.add_argument("--repeat-last", action="store_true", help="resend the previous event_key")
    _add_signing_faults(session_log)

    booking = commands.add_parser("booking", help="agent booking actions")
    booking_commands = booking.add_subparsers(dest="booking_action", required=True)
    for action in ("validate", "check-in", "complete", "extend"):
        sub = booking_commands.add_parser(action)
        sub.add_argument("--code", required=True)
        if action == "extend":
            when = sub.add_mutually_exclusive_group(required=True)
            when.add_argument("--to", help="new end, ISO 8601")
            when.add_argument("--by", type=parse_duration, help="add to the current end, e.g. 30m")
        _add_signing_faults(sub)

    session = commands.add_parser("session", help="a full workstation login with a booking code")
    session.add_argument("--user", dest="session_user", required=True, help="@persona or username")
    session.add_argument("--code", required=True)
    session.add_argument("--minutes", type=float, default=1)
    session.add_argument("--extend-by", type=parse_duration, default=None)
    session.add_argument("--no-complete", action="store_true")

    agents = commands.add_parser("agents", help="operator: list or show agents")
    agents_commands = agents.add_subparsers(dest="agents_action", required=True)
    agents_list = agents_commands.add_parser("list")
    agents_list.add_argument("--equipment-uid")
    agents_list.add_argument("--state")
    agents_commands.add_parser("show").add_argument("agent", type=int)

    grant = commands.add_parser("grant", help="operator: enrollment grants")
    grant_commands = grant.add_subparsers(dest="grant_action", required=True)
    grant_create = grant_commands.add_parser("create")
    which = grant_create.add_mutually_exclusive_group(required=True)
    which.add_argument("--equipment", help="stub lab key or equipment UID (new agent)")
    which.add_argument("--agent", type=int, help="existing agent id (re-enrollment)")
    grant_create.add_argument("--ttl", type=int, default=15)
    grant_commands.add_parser("list").add_argument("--agent", type=int, required=True)
    grant_revoke = grant_commands.add_parser("revoke")
    grant_revoke.add_argument("--agent", type=int, required=True)
    grant_revoke.add_argument("--grant", type=int, required=True)

    for name in ("revoke", "decommission"):
        commands.add_parser(name, help=f"operator: {name} an agent").add_argument("--agent", type=int, required=True)

    for name, help_text in (("send", "send any signed request"), ("headers", "print signed headers only")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("method")
        sub.add_argument("path")
        sub.add_argument("--json", default="", help="raw JSON body, sent and signed exactly as given")
        _add_signing_faults(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key_file = profile_path(args.profile) if args.profile else (args.key_file or DEFAULT_KEY_FILE)
    base_url = args.global_base_url or DEFAULT_BASE_URL
    as_persona = args.persona.removeprefix("@")

    def show(result: HttpResult) -> int:
        print(dump(result))
        return 0 if result.ok else 1

    if args.command == "enroll":
        result, agent = enroll(
            base_url=args.base_url,
            agent_uid=args.agent_uid,
            grant=args.grant,
            key_file=key_file,
            equipment_uid=args.equipment_uid,
        )
        print(dump(result))
        if agent:
            print(f"Stub agent key written to {key_file}")
        return 0 if agent else 1
    if args.command == "provision":
        profile = args.profile or args.equipment
        result, agent = provision(persona=as_persona, equipment=args.equipment, profile=profile, base_url=base_url)
        print(dump(result))
        if agent:
            print(f"Agent {agent.agent_uid} enrolled; profile '{profile}' at {profile_path(profile)}")
        return 0 if agent else 1
    if args.command == "profiles":
        directory = state_home() / "agents"
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            state = read_json(path) or {}
            print(f"{path.stem:<12} agent={state.get('agent_uid')} equipment={state.get('equipment_uid')}")
        return 0
    if args.command == "info":
        return show(http(base_url, "GET", "/agent/info"))
    if args.command == "agents":
        if args.agents_action == "list":
            query = "&".join(
                f"{name}={value}"
                for name, value in (("equipment_uid", args.equipment_uid), ("state", args.state))
                if value
            )
            return show(_operator(as_persona, "GET", "/api/agents" + (f"?{query}" if query else "")))
        return show(_operator(as_persona, "GET", f"/api/agents/{args.agent}"))
    if args.command == "grant":
        if args.grant_action == "create":
            if args.equipment:
                body = {"equipment_uid": resolve_equipment_uid(args.equipment), "ttl_minutes": args.ttl}
                return show(_operator(as_persona, "POST", "/api/agents", body))
            body = {"ttl_minutes": args.ttl}
            return show(_operator(as_persona, "POST", f"/api/agents/{args.agent}/enrollment-grants", body))
        if args.grant_action == "list":
            return show(_operator(as_persona, "GET", f"/api/agents/{args.agent}/enrollment-grants"))
        revoke_path = f"/api/agents/{args.agent}/enrollment-grants/{args.grant}/actions/revoke"
        return show(_operator(as_persona, "POST", revoke_path, {}))
    if args.command in {"revoke", "decommission"}:
        return show(_operator(as_persona, "POST", f"/api/agents/{args.agent}/actions/{args.command}", {}))

    agent = StubAgent.load(key_file)
    if args.global_base_url:
        agent.base_url = args.global_base_url
    faults = _signing_faults(args)
    if args.command == "heartbeat":
        status = 0
        for index in range(max(args.count, 1)):
            result = agent.heartbeat(faults)
            print(dump(result))
            status = status or (0 if result.ok else 1)
            if args.every and index + 1 < args.count:
                time.sleep(args.every)
        return status
    if args.command == "activity":
        return show(
            agent.activity(
                faults,
                status=args.status,
                remote_user=args.remote_user,
                remote_user_display_name=args.remote_user_display_name,
                remote_computer=args.remote_computer,
                remote_ip=args.remote_ip,
                booking_code=args.booking_code,
            )
        )
    if args.command == "session-log":
        event_key = agent.last_event_key if args.repeat_last else args.event_key
        if args.repeat_last and not event_key:
            raise SystemExit("No previous session log to repeat.")
        return show(
            agent.session_log(
                remote_user=args.remote_user,
                minutes=args.minutes,
                booking_code=args.booking_code,
                event_key=event_key,
                faults=faults,
            )
        )
    if args.command == "booking":
        if args.booking_action == "extend":
            if args.by is not None:
                return show(agent.extend_by(args.code, args.by, faults))
            return show(agent.booking("extend", args.code, faults, ends_at=args.to))
        return show(agent.booking(args.booking_action, args.code, faults))
    if args.command == "session":
        ok = run_session(
            agent,
            user=args.session_user,
            code=args.code,
            minutes=args.minutes,
            extend_by=args.extend_by,
            complete=not args.no_complete,
        )
        return 0 if ok else 1
    # send / headers
    method, path, body = args.method.upper(), args.path, args.json.encode()
    if args.command == "headers":
        for header, value in agent.signed_headers(method, path, body, faults).items():
            print(f"{header}: {value}")
        return 0
    return show(agent.send(method, path, body, faults))


if __name__ == "__main__":
    sys.exit(main())
