"""Test helper: build X-Agent-* headers the way an agent device signs a request."""

import base64
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.agents.application import agent_request_message


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def signed_headers(
    private_key: Ed25519PrivateKey,
    agent_uid,
    body: bytes,
    *,
    method: str = "POST",
    path: str = "/agent/heartbeat",
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or b64url(secrets.token_bytes(16))
    message = agent_request_message(
        agent_uid=str(agent_uid), method=method, path=path, timestamp=ts, nonce=nonce, body=body
    )
    return {
        "HTTP_X_AGENT_ID": str(agent_uid),
        "HTTP_X_AGENT_TIMESTAMP": ts,
        "HTTP_X_AGENT_NONCE": nonce,
        "HTTP_X_AGENT_SIGNATURE": b64url(private_key.sign(message)),
    }
