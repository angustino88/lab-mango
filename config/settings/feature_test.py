"""Fresh-schema feature tests only, never a deployment/migration configuration.

Requires an explicitly provisioned loopback PostgreSQL cluster and synthetic
role. This bypasses the legacy migration graph to test current model behavior;
it does not validate a migration or data-transfer path for existing databases.
"""

from .test import *  # noqa: F403
from .test import env

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "rest_framework_api_key",
    "core.common",
    "core.reference_data.apps.ReferenceDataConfig",
    "core.users",
    "core.labs",
]
MIGRATION_MODULES = {
    app: None
    for app in ("auth", "contenttypes", "sessions", "common", "reference_data", "users", "labs")
}
ROOT_URLCONF = "core.labs.api_urls"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": "labmango_feature_test",
        "HOST": "127.0.0.1",
        "PORT": env.int("LABMANGO_FEATURE_TEST_PORT"),
        "TEST": {"NAME": "test_labmango_features"},
    },
}
