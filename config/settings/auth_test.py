"""Isolated synthetic auth tests; never connect to configured application databases."""

import os

from .test import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": "labmango_auth_test",
        "HOST": "127.0.0.1",
        "PORT": int(os.environ["LABMANGO_AUTH_TEST_PORT"]),
        "TEST": {"NAME": "test_labmango_auth"},
    }
}
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_api_key",
    "rest_framework_simplejwt.token_blacklist",
    "core.users",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
ROOT_URLCONF = "core.users.tests.auth_urls"
SPECTACULAR_SETTINGS = {**SPECTACULAR_SETTINGS, "ENUM_NAME_OVERRIDES": {}}  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
