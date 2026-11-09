"""
Test settings — fast, isolated, no external services required.
"""
from .base import *  # noqa
from .base import env

# URS sync fails closed without a token; tests mock HTTP and need a non-empty value.
URS_ACCESS_TOKEN = "test-urs-token"

# Routing sync test bearer token hash
ROUTING_SYNC_STATIC_TOKEN_HASHES = [
    "08395c55c808b4b41ca052637fe71538606fc0dbe0474bbec8a5059bf14c1909",
]

# GENERAL
# ------------------------------------------------------------------------------
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="test-secret-key-only-for-ci-not-for-production",
)
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# DATABASES
# ------------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://labmango:labmango@localhost:5432/labmango_test",
    ),
}

# CACHES  (in-memory, no Redis needed for tests)
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}

# PASSWORDS  (fast hasher for test speed)
# ------------------------------------------------------------------------------
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# CELERY  (run tasks synchronously in tests)
# ------------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# LDAP
# ------------------------------------------------------------------------------
LDAP_AUTH_URL = "ldaps://de.bosch.com:3269"
LDAP_AUTH_CA_CERT_FILE = None
