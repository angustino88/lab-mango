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


