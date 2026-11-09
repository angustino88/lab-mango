"""Synthetic, network-free regressions for Entra authentication diagnostics."""

import logging
import socket
from unittest.mock import Mock
from urllib.error import URLError

import jwt
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from core.users.features.auth.aad_login import service

TOKEN = "synthetic-secret-id-token"
CHALLENGE = "synthetic-secret-malformed-challenge"
NONCE = "synthetic-secret-nonce"
SUBJECT = "synthetic-secret-subject"
DEPENDENCY_SECRET = "synthetic-secret-proxy-credential"
TUNNEL_ERROR = "Tunnel connection failed: 501 Not Implemented"
DEPENDENCY_MESSAGE = "Entra JWKS connection failed"
REJECTION_MESSAGE = "Entra authentication rejected"
SENSITIVE_TEXT = (TOKEN, CHALLENGE, NONCE, SUBJECT, DEPENDENCY_SECRET, TUNNEL_ERROR)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block outbound connections, allowing Windows asyncio's local socketpair."""

    def unexpected_connection(*args: object, **kwargs: object) -> None:
        pytest.fail("Real network access is forbidden in logging regression tests")

    monkeypatch.setattr(socket, "create_connection", unexpected_connection)
    monkeypatch.setattr("jwt.jwks_client.urllib.request.urlopen", unexpected_connection)


@pytest.fixture
def jwks_connection_error(monkeypatch: pytest.MonkeyPatch) -> jwt.PyJWKClientConnectionError:
    """Keep the real exception chain while replacing only the JWKS boundary."""
    try:
        try:
            raise URLError(TUNNEL_ERROR)
        except URLError as cause:
            raise jwt.PyJWKClientConnectionError(f"JWKS fetch failed: {DEPENDENCY_SECRET}") from cause
    except jwt.PyJWKClientConnectionError as error:
        client = Mock(spec=jwt.PyJWKClient)
        client.get_signing_key_from_jwt.side_effect = error
        monkeypatch.setattr(service, "_jwks_client", Mock(return_value=client))
        return error


def assert_safe_diagnostics(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    expected: list[tuple[int, str]],
) -> None:
    """Check records as well as formatted output, including hidden logging args."""
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    records = [record for record in caplog.records if record.name == service.logger.name]
    assert [(record.levelno, record.getMessage()) for record in records] == expected
    for record in records:
        assert record.exc_info is None
        assert record.exc_text is None
        assert record.stack_info is None
    diagnostics = caplog.text + repr([vars(record) for record in caplog.records])
    assert "Traceback" not in diagnostics
    for text in SENSITIVE_TEXT:
        assert text not in diagnostics


def assert_connection_chaining(
    error: service.AADAuthError,
    connection_error: jwt.PyJWKClientConnectionError,
) -> None:
    assert error.code == "invalid_sso_token"
    assert str(error) == "invalid_sso_token"
    assert error.__cause__ is connection_error
    assert isinstance(connection_error.__cause__, URLError)
    assert connection_error.__cause__.reason == TUNNEL_ERROR


def test_jwks_connection_failure_logs_one_safe_warning_and_preserves_chaining(
    jwks_connection_error: jwt.PyJWKClientConnectionError,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger=service.logger.name)

    with pytest.raises(service.AADAuthError) as raised:
        service._decode_id_token(TOKEN)

    assert_connection_chaining(raised.value, jwks_connection_error)
    assert_safe_diagnostics(caplog, capsys, [(logging.WARNING, DEPENDENCY_MESSAGE)])


def test_real_jwks_client_wraps_tunnel_failure_and_logs_at_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.WARNING, logger=service.logger.name)
    tunnel_error = URLError(OSError(TUNNEL_ERROR))
    monkeypatch.setattr("jwt.jwks_client.urllib.request.urlopen", Mock(side_effect=tunnel_error))
    client = jwt.PyJWKClient("https://identity.example.invalid/jwks")
    monkeypatch.setattr(service, "_jwks_client", Mock(return_value=client))
    token = jwt.encode({"sub": SUBJECT}, key="", algorithm="none", headers={"kid": "synthetic-key"})

    with pytest.raises(service.AADAuthError) as raised:
        service._decode_id_token(token)

    assert raised.value.code == "invalid_sso_token"
    connection_error = raised.value.__cause__
    assert isinstance(connection_error, jwt.PyJWKClientConnectionError)
    assert connection_error.__cause__ is tunnel_error
    assert_safe_diagnostics(caplog, capsys, [(logging.WARNING, DEPENDENCY_MESSAGE)])
    assert token not in caplog.text


def test_invalid_token_logs_one_safe_info_and_preserves_chaining(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger=service.logger.name)
    error = jwt.InvalidTokenError(f"Invalid token: {TOKEN} {DEPENDENCY_SECRET}")
    client = Mock(spec=jwt.PyJWKClient)
    monkeypatch.setattr(service, "_jwks_client", Mock(return_value=client))
    monkeypatch.setattr(service.jwt, "decode", Mock(side_effect=error))

    with pytest.raises(service.AADAuthError) as raised:
        service._decode_id_token(TOKEN)

    assert raised.value.code == "invalid_sso_token"
    assert str(raised.value) == "invalid_sso_token"
    assert raised.value.__cause__ is error
    assert_safe_diagnostics(caplog, capsys, [(logging.INFO, REJECTION_MESSAGE)])


def test_aad_login_failed_decode_never_prints_token_or_challenge(
    jwks_connection_error: jwt.PyJWKClientConnectionError,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger=service.logger.name)

    with pytest.raises(service.AADAuthError) as raised:
        service.aad_login(id_token=TOKEN, challenge_id=CHALLENGE)

    assert_connection_chaining(raised.value, jwks_connection_error)
    # Check printing first so the token-print regression is independent of log classification.
    assert_safe_diagnostics(caplog, capsys, [(logging.WARNING, DEPENDENCY_MESSAGE)])


def test_aad_login_decoded_payload_never_prints_before_malformed_challenge(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger=service.logger.name)
    payload: dict[str, str] = {"nonce": NONCE, "sub": SUBJECT, "synthetic_secret": DEPENDENCY_SECRET}
    monkeypatch.setattr(service, "_decode_id_token", Mock(return_value=payload))

    with pytest.raises(service.AADAuthError) as raised:
        service.aad_login(id_token=TOKEN, challenge_id=CHALLENGE)

    assert raised.value.code == "invalid_sso_token"
    assert isinstance(raised.value.__cause__, ValueError)
    assert_safe_diagnostics(caplog, capsys, [])


def test_endpoint_jwks_failure_keeps_401_contract_without_detail_leaks(
    api_client: APIClient,
    jwks_connection_error: jwt.PyJWKClientConnectionError,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG, logger=service.logger.name)
    cache.clear()
    try:
        response = api_client.post("/api/aad-login", {"id_token": TOKEN}, format="json")
    finally:
        cache.clear()

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "invalid_sso_token"
    assert body["error"]["message"] == "Microsoft Token is invalid or expired"
    serialized = response.content.decode()
    for text in (*SENSITIVE_TEXT, "Traceback", "PyJWKClientConnectionError", "URLError", "jwks_fetch"):
        assert text not in serialized
    assert_safe_diagnostics(caplog, capsys, [(logging.WARNING, DEPENDENCY_MESSAGE)])
