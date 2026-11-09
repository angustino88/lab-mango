"""Opt into the synthetic current-model schema only under feature_test settings."""

import pytest
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import include, path

urlpatterns = [path("api/", include("core.labs.api_urls"))]

if settings.SETTINGS_MODULE == "config.settings.feature_test":
    from tests.feature_db import django_db_setup  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_api_settings(settings):
    cache.clear()
    if "allauth.account" not in settings.INSTALLED_APPS:
        settings.MIDDLEWARE = [
            middleware for middleware in settings.MIDDLEWARE if not middleware.startswith("allauth.")
        ]
        settings.ROOT_URLCONF = __name__
    ContentType.objects.clear_cache()
    yield
    ContentType.objects.clear_cache()
    cache.clear()
