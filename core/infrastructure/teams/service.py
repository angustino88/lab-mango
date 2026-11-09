import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TeamsPostCode(str, Enum):
    """Stable outcome codes for a Teams webhook POST."""

    ACCEPTED = "accepted"
    HTTP_FAILED = "http_failed"
    RETRYABLE_HTTP = "retryable_http"
    RETRYABLE_TRANSPORT = "retryable_transport"
    REQUEST_FAILED = "request_failed"


class TeamsProxyPolicy(str, Enum):
    """Select whether the request may use process proxy settings."""

    DISABLED = "disabled"
    EXPLICIT = "explicit"


@dataclass(frozen=True, slots=True)
class TeamsPostResult:
    sent: bool
    retryable: bool
    code: TeamsPostCode
    status_code: int | None = None


def post_teams_json(
    url: str,
    payload: Mapping[str, Any],
    timeout: tuple[float, float] = (3.0, 5.0),
    proxy_policy: TeamsProxyPolicy | str = TeamsProxyPolicy.DISABLED,
) -> TeamsPostResult:
    """Make one bounded JSON POST and report a sanitized outcome."""
    try:
        policy = TeamsProxyPolicy(proxy_policy)
    except ValueError:
        raise ValueError(f"Unsupported Teams proxy policy: {proxy_policy!r}") from None

    proxies = None
    if policy is TeamsProxyPolicy.EXPLICIT:
        configured_proxies = {
            "http": getattr(settings, "HTTP_PROXY", None),
            "https": getattr(settings, "HTTPS_PROXY", None),
        }
        proxies = {scheme: proxy for scheme, proxy in configured_proxies.items() if proxy}

    result: TeamsPostResult
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
                proxies=proxies,
                allow_redirects=False,
                stream=True,
            )
            try:
                status_code = response.status_code
                if 200 <= status_code < 300:
                    result = TeamsPostResult(True, False, TeamsPostCode.ACCEPTED, status_code)
                elif status_code in {408, 425, 429} or 500 <= status_code < 600:
                    result = TeamsPostResult(False, True, TeamsPostCode.RETRYABLE_HTTP, status_code)
                else:
                    result = TeamsPostResult(False, False, TeamsPostCode.HTTP_FAILED, status_code)
            finally:
                response.close()
    except (requests.Timeout, requests.ConnectionError):
        result = TeamsPostResult(False, True, TeamsPostCode.RETRYABLE_TRANSPORT)
    except requests.RequestException:
        result = TeamsPostResult(False, False, TeamsPostCode.REQUEST_FAILED)

    if not result.sent:
        logger.warning("Teams webhook POST outcome: code=%s status=%s", result.code.value, result.status_code)
    return result


def send_ms_teams_notification(url: str, payload: dict) -> bool:
    """Compatibility wrapper for OTP delivery; returns whether Teams accepted it."""
    result = post_teams_json(
        url,
        payload,
        timeout=(3.0, 5.0),
        proxy_policy=TeamsProxyPolicy.EXPLICIT,
    )
    # Preserve the legacy endpoint's exact-success contract for existing OTP callers.
    return result.sent and result.status_code == 200
