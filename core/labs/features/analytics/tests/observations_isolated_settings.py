"""Synthetic settings for observation contracts; no env files or database backend."""

from tests.notification_isolated_settings import *  # noqa: F403
from tests.notification_isolated_settings import INSTALLED_APPS as BASE_INSTALLED_APPS

EXTRA_APPS = "rest_framework rest_framework_api_key core.agents core.routing core.websocket"
INSTALLED_APPS = BASE_INSTALLED_APPS + EXTRA_APPS.split()
ALLOWED_HOSTS = ["testserver"]
ROOT_URLCONF = "core.labs.features.analytics.tests.test_observations_contract"
REST_FRAMEWORK = {"DEFAULT_SCHEMA_CLASS": "config.schema.ProjectAutoSchema"}
SPECTACULAR_SETTINGS = {"TITLE": "Synthetic observation contracts", "VERSION": "test", "OAS_VERSION": "3.1.0"}
