from unittest.mock import Mock

import pytest
import requests
from django.test import override_settings

from core.infrastructure.teams.service import (
    TeamsPostCode,
    TeamsProxyPolicy,
    post_teams_json,
    send_ms_teams_notification,
)


@pytest.mark.parametrize(
    ("status_code", "sent", "retryable", "code"),
    [
        (200, True, False, TeamsPostCode.ACCEPTED),
        (204, True, False, TeamsPostCode.ACCEPTED),
        (408, False, True, TeamsPostCode.RETRYABLE_HTTP),
        (425, False, True, TeamsPostCode.RETRYABLE_HTTP),
        (429, False, True, TeamsPostCode.RETRYABLE_HTTP),
        (503, False, True, TeamsPostCode.RETRYABLE_HTTP),
        (301, False, False, TeamsPostCode.HTTP_FAILED),
        (400, False, False, TeamsPostCode.HTTP_FAILED),
    ],
)
def test_post_teams_json_classifies_http_status_and_closes_response(monkeypatch, status_code, sent, retryable, code):
    response = Mock(status_code=status_code)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))

    result = post_teams_json("https://teams.invalid/hook", {"value": "test"})

    assert (result.sent, result.retryable, result.code, result.status_code) == (
        sent,
        retryable,
        code,
        status_code,
    )
    response.close.assert_called_once_with()
    assert session.trust_env is False
    session.post.assert_called_once_with(
        "https://teams.invalid/hook",
        json={"value": "test"},
        headers={"Content-Type": "application/json"},
        timeout=(3.0, 5.0),
        proxies=None,
        allow_redirects=False,
        stream=True,
    )


@pytest.mark.parametrize(
    ("exception", "retryable", "code"),
    [
        (requests.Timeout("timeout"), True, TeamsPostCode.RETRYABLE_TRANSPORT),
        (requests.ConnectionError("disconnected"), True, TeamsPostCode.RETRYABLE_TRANSPORT),
        (requests.RequestException("invalid request"), False, TeamsPostCode.REQUEST_FAILED),
    ],
)
def test_post_teams_json_classifies_request_exceptions(monkeypatch, exception, retryable, code):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.side_effect = exception
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))

    result = post_teams_json("https://teams.invalid/hook", {})

    assert result.sent is False
    assert result.retryable is retryable
    assert result.code is code
    assert result.status_code is None


@override_settings(HTTP_PROXY="http://proxy.invalid", HTTPS_PROXY="https://proxy.invalid")
def test_legacy_wrapper_uses_explicit_settings_proxies_and_preserves_200_contract(monkeypatch):
    response = Mock(status_code=200)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))

    assert send_ms_teams_notification("https://teams.invalid/hook", {"x": 1}) is True

    kwargs = session.post.call_args.kwargs
    assert kwargs["proxies"] == {"http": "http://proxy.invalid", "https": "https://proxy.invalid"}
    assert kwargs["timeout"] == (3.0, 5.0)
    assert session.trust_env is False
    response.close.assert_called_once_with()


def test_legacy_wrapper_does_not_treat_non_200_success_as_accepted(monkeypatch):
    response = Mock(status_code=202)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))

    assert send_ms_teams_notification("https://teams.invalid/hook", {"x": 1}) is False
    response.close.assert_called_once_with()


@override_settings(HTTP_PROXY="", HTTPS_PROXY="")
def test_explicit_proxy_policy_with_no_configured_proxies_passes_empty_mapping(
    monkeypatch,
):
    response = Mock(status_code=200)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))

    result = post_teams_json("https://teams.invalid/hook", {}, proxy_policy=TeamsProxyPolicy.EXPLICIT)

    assert result.sent is True
    assert session.post.call_args.kwargs["proxies"] == {}
