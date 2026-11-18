"""Fixtures for the local identity stub tests (tools/stubs)."""

import pytest
from django.core.cache import cache

from tools.stubs.entra import StubIssuer
from tools.stubs.testing import stub_entra_environment


@pytest.fixture(scope="session")
def stub_issuer() -> StubIssuer:
    return StubIssuer.generate()


@pytest.fixture()
def stub_home(tmp_path, monkeypatch):
    """Keep stub state (generations, sessions, agent keys) out of the developer's home directory."""
    monkeypatch.setenv("LABMANGO_STUB_HOME", str(tmp_path / "stub-home"))
    return tmp_path / "stub-home"


@pytest.fixture(autouse=True)
def _fresh_throttles():
    """Login throttles live in the cache; the stubs log in often, so each test starts with a clean count."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def stub_env(stub_issuer, stub_home):
    stub_issuer.save()  # as `entra init` does: CLI paths (agent provision, call_as) load it from LABMANGO_STUB_HOME
    with stub_entra_environment(stub_issuer):
        yield stub_issuer
