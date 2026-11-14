"""
Root conftest — shared pytest fixtures for the entire project.
"""
import sys
from pathlib import Path

import pytest
from rest_framework.test import APIClient

LOCAL_CONTRACTS_SRC = Path(__file__).parent / "packages" / "drf-api-contracts" / "src"
sys.path.insert(0, str(LOCAL_CONTRACTS_SRC))


def test_new_labs_features_do_not_reference_legacy_features_or_models():
    """Keep the new feature tree independent from retired model names."""
    feature_root = Path(__file__).parent / "core" / "labs" / "features"
    forbidden = ("LabComputer", "models.equipment.computer")
    violations = []
    for path in feature_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            if value in text:
                violations.append(f"{path}: {value}")
    assert not violations, "Forbidden legacy references found:\n" + "\n".join(violations)


@pytest.fixture(autouse=True)
def media_storage(settings, tmpdir):
    settings.MEDIA_ROOT = tmpdir.strpath


_RESPONSE_CONTRACT = None


def _response_contract():
    global _RESPONSE_CONTRACT
    if _RESPONSE_CONTRACT is None:
        from core.common.openapi.response_contract import ResponseContract

        _RESPONSE_CONTRACT = ResponseContract.from_file()
    return _RESPONSE_CONTRACT


@pytest.fixture(autouse=True)
def openapi_response_contract(request, settings, monkeypatch):
    """DOC-4: every JSON response a test receives through Django's test clients matches the committed schema.

    Only the project URLconf is checked (tests that swap ROOT_URLCONF route to synthetic views). A response that
    is not documented for its status is not checked here. Set ``RESPONSE_CONTRACT_REPORT=<file>`` to record
    mismatches instead of failing.
    """
    import json
    import os

    from django.test.client import AsyncClient, Client

    if request.node.get_closest_marker("skip_response_contract"):
        yield
        return
    report_path = os.environ.get("RESPONSE_CONTRACT_REPORT")
    found: list[str] = []

    def check(response):
        if settings.ROOT_URLCONF != "config.urls":
            return
        content_type = response.get("Content-Type", "") if hasattr(response, "get") else ""
        if not content_type.startswith("application/json") or getattr(response, "streaming", False):
            return
        method = response.request.get("REQUEST_METHOD", "GET")
        path = response.request.get("PATH_INFO", "")
        try:
            body = json.loads(response.content or b"null")
        except ValueError:
            return
        contract = _response_contract()
        errors = contract.violations(method, path, response.status_code, body)
        if errors:
            found.append(f"{contract.key(method, path, response.status_code)}: " + "; ".join(errors))

    original_sync, original_async = Client.request, AsyncClient.request

    def sync_request(self, **request_kwargs):
        response = original_sync(self, **request_kwargs)
        check(response)
        return response

    async def async_request(self, **request_kwargs):
        response = await original_async(self, **request_kwargs)
        check(response)
        return response

    monkeypatch.setattr(Client, "request", sync_request)
    monkeypatch.setattr(AsyncClient, "request", async_request)
    yield
    if not found:
        return
    if report_path:
        with open(report_path, "a", encoding="utf-8") as handle:
            for line in found:
                handle.write(f"{request.node.nodeid}\t{line}\n")
        return
    pytest.fail("Responses do not match the OpenAPI schema (DOC-4):\n" + "\n".join(dict.fromkeys(found)), pytrace=False)


@pytest.fixture()
def user(db):
    from tests.factories import UserFactory
    return UserFactory(username="testuser")


@pytest.fixture()
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture()
def authenticated_client(user, api_client) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


