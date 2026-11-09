"""Isolate reference API tests from other concurrently running local suites."""

import pytest


@pytest.fixture(autouse=True)
def expose_unexpected_errors(monkeypatch):
    from core.common.api import exceptions

    original = exceptions.api_exception_handler

    def handler(error, context):
        response = original(error, context)
        if response is not None and response.status_code == 500:
            raise error
        return response

    monkeypatch.setattr(exceptions, "api_exception_handler", handler)


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings_parallel_suffix):
    from django.conf import settings

    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = "test_labmango_reference_imports"
