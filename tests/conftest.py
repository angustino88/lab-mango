"""Opt-in schema isolation; normal tests retain pytest-django's setup."""

from django.conf import settings

if settings.SETTINGS_MODULE == "config.settings.feature_test":
    from tests.feature_db import django_db_setup  # noqa: F401
