"""Explicit disposable loopback PostgreSQL only; no application/env-file loaders.

CI must provide a dedicated cluster and role with CREATEDB, never a shared server.
No credentials are read here. Local execution is deliberately opt-in.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from tests.notification_isolated_settings import *  # noqa: F403

if os.environ.get("LABMANGO_NOTIFICATION_DISPOSABLE_PG") != "yes-disposable-local-cluster":
    raise ImproperlyConfigured("Disposable notification PostgreSQL tests require explicit opt-in.")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": "55439",
        "NAME": "notification_disposable_control",
        "USER": "notification_disposable_test",
        "PASSWORD": "",
        "OPTIONS": {"connect_timeout": 3, "options": "-c statement_timeout=10000 -c lock_timeout=3000"},
    }
}
