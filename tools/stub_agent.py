"""Stub agent for testing the signed ``/agent/...`` endpoints by hand (development and test only).

Apidog and similar tools cannot easily produce the Ed25519 request signature, so this client does it:

    # 1. A coordinator creates an enrollment grant for a computing unit (operator API or admin):
    #    POST /api/agents  {"equipment_uid": "<uid>"}  ->  agent_uid + grant (shown once)
    # 2. Enroll a stub agent; its private key is written to --key-file (default ~/.labmango-stub-agent.json):
    python tools/stub_agent.py enroll --base-url http://localhost:8000 --agent-uid <agent_uid> --grant <grant>
    # 3. Send signed requests as that agent:
    python tools/stub_agent.py heartbeat
    python tools/stub_agent.py activity --status active --remote-user alice --booking-code BK-1
    python tools/stub_agent.py send PATCH /agent/equipment/activity --json '{"status": "free"}'
    # Or print one set of signed headers to paste into Apidog (single use, valid for the server's clock
    # skew window, AGENT_REQUEST_MAX_SKEW_S, 300 s by default). The body must be sent byte for byte:
    python tools/stub_agent.py headers PATCH /agent/equipment/activity --json '{"status":"free"}'

The key file holds a private key. Keep it outside the repository and never use it for a real device.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Must match core/agents/application.py (ENROLLMENT_CONTEXT, REQUEST_SIGNATURE_CONTEXT, agent_request_message).
ENROLLMENT_CONTEXT = b"labmango-enroll-v1"
REQUEST_SIGNATURE_CONTEXT = b"labmango-agent-request-v1"
DEFAULT_KEY_FILE = Path.home() / ".labmango-stub-agent.json"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def http(base_url: str, method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body if method != "GET" else None,
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw.decode("utf-8", "replace")


class StubAgent:
    def __init__(self, key_file: Path):
        state = json.loads(key_file.read_text())
        self.base_url: str = state["base_url"]
        self.backend_id: str = state["backend_id"]
        self.agent_uid: str = state["agent_uid"]
        self.key = Ed25519PrivateKey.from_private_bytes(b64url_decode(state["private_key"]))

    def signed_headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        timestamp = str(int(time.time()))
        nonce = b64url(secrets.token_bytes(16))
        message = b"\0".join(
            (
                REQUEST_SIGNATURE_CONTEXT,
                self.backend_id.encode("ascii"),
                self.agent_uid.encode("ascii"),
                method.upper().encode("ascii"),
                path.encode("utf-8"),
                timestamp.encode("ascii"),
                nonce.encode("ascii"),
                hashlib.sha256(body).hexdigest().encode("ascii"),
            )
        )
        return {
            "X-Agent-Id": self.agent_uid,
            "X-Agent-Timestamp": timestamp,
            "X-Agent-Nonce": nonce,
            "X-Agent-Signature": b64url(self.key.sign(message)),
        }

    def send(self, method: str, path: str, body: bytes) -> tuple[int, Any]:
        return http(self.base_url, method.upper(), path, body, self.signed_headers(method, path, body))


def enroll(args: argparse.Namespace) -> int:
    status, info = http(args.base_url, "GET", "/agent/info", b"", {})
    if status != 200:
        print(f"GET /agent/info failed: {status} {info}", file=sys.stderr)
        return 1
    backend_id = info["data"]["backend_key"]
    key = Ed25519PrivateKey.generate()
    der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    proof = key.sign(
        b"\0".join(
            (
                ENROLLMENT_CONTEXT,
                backend_id.encode("ascii"),
                args.agent_uid.encode("ascii"),
                hashlib.sha256(args.grant.encode()).hexdigest().encode("ascii"),
                der,
            )
        )
    )
    payload = {
        "grant": args.grant,
        "public_key": b64url(der),
        "key_storage": "software",
        "fingerprint": "stub-agent",
        "agent_version": "stub-0",
        "proof": b64url(proof),
    }
    status, result = http(args.base_url, "POST", "/agent/enrollments", json.dumps(payload).encode(), {})
    print(status, json.dumps(result, indent=2, default=str))
    if status >= 300:
        return 1
    raw = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    state = {
        "base_url": args.base_url,
        "backend_id": backend_id,
        "agent_uid": args.agent_uid,
        "private_key": b64url(raw),
    }
    descriptor = os.open(args.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(state, handle)
    print(f"Stub agent key written to {args.key_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    commands = parser.add_subparsers(dest="command", required=True)

    enroll_parser = commands.add_parser("enroll", help="Enroll a stub agent with a one-time grant")
    enroll_parser.add_argument("--base-url", required=True)
    enroll_parser.add_argument("--agent-uid", required=True)
    enroll_parser.add_argument("--grant", required=True)

    commands.add_parser("heartbeat", help="POST /agent/heartbeat")

    activity = commands.add_parser("activity", help="PATCH /agent/equipment/activity")
    activity.add_argument("--status", choices=["offline", "free", "active", "inactive", "maintaining"])
    for name in ("remote-user", "remote-user-display-name", "remote-computer", "remote-ip", "booking-code"):
        activity.add_argument(f"--{name}")

    for name, help_text in (("send", "Send any signed request"), ("headers", "Print signed headers only")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("method")
        sub.add_argument("path")
        sub.add_argument("--json", default="", help="Raw JSON body, sent and signed exactly as given")

    args = parser.parse_args(argv)
    if args.command == "enroll":
        return enroll(args)

    agent = StubAgent(args.key_file)
    if args.command == "heartbeat":
        method, path, body = "POST", "/agent/heartbeat", b"{}"
    elif args.command == "activity":
        fields = {
            key: value
            for key, value in {
                "status": args.status,
                "remote_user": args.remote_user,
                "remote_user_display_name": args.remote_user_display_name,
                "remote_computer": args.remote_computer,
                "remote_ip": args.remote_ip,
                "booking_code": args.booking_code,
            }.items()
            if value is not None
        }
        method, path, body = "PATCH", "/agent/equipment/activity", json.dumps(fields).encode()
    else:
        method, path, body = args.method.upper(), args.path, args.json.encode()
        if args.command == "headers":
            for header, value in agent.signed_headers(method, path, body).items():
                print(f"{header}: {value}")
            return 0
    status, result = agent.send(method, path, body)
    print(status, json.dumps(result, indent=2, default=str))
    return 0 if status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
