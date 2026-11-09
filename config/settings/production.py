import logging
import warnings

from urllib3.exceptions import InsecureRequestWarning

from .base import *  # noqa
from .base import env

# No LDAP, local password, allauth signup or password-reset authentication in production.
ENTRA_SSO_ONLY = True
AUTHENTICATION_BACKENDS = ["core.users.backends.EntraSessionBackend"]
ACCOUNT_ALLOW_REGISTRATION = False
DJANGO_ADMIN_FORCE_ALLAUTH = False
LOGIN_URL = ENTRA_FRONTEND_LOGIN_URL
REFRESH_TOKEN_COOKIE_SECURE = True
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": ("core.users.features.auth.authentication.EntraJWTAuthentication",),
}

# InsecureRequestWarning suppression removed per ARCH-002.
# Only suppress at the specific call-site if intentionally bypassing verification.

# GENERAL
# ------------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["example.com"])

# DATABASES
# ------------------------------------------------------------------------------
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": False,
        },
    }
}

# SECURITY
# ------------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOWED_ORIGIN_REGEXES = env.list("DJANGO_CORS_ALLOWED_ORIGIN_REGEXES", default=[])
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
SECURE_CONTENT_TYPE_NOSNIFF = env.bool("DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True)

# STORAGES / MINIO
# ------------------------------------------------------------------------------
MINIO_ENABLED = env.bool("USE_MINIO", default=False)

if MINIO_ENABLED:
    MINIO_ACCESS_KEY = env("MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY = env("MINIO_SECRET_KEY")
    MINIO_BUCKET = env("MINIO_BUCKET")
    MINIO_ENDPOINT = env("MINIO_ENDPOINT")
    MINIO_REGION = env("MINIO_REGION", default="us-east-1")
    MINIO_USE_SSL = env.bool("MINIO_USE_SSL", default=False)
    MINIO_SIGNATURE_VERSION = env("MINIO_SIGNATURE_VERSION", default="s3v4")
    MINIO_QUERYSTRING_AUTH = env.bool("MINIO_QUERYSTRING_AUTH", default=False)
    MINIO_FILE_OVERWRITE = env.bool("MINIO_FILE_OVERWRITE", default=False)
    MINIO_DEFAULT_ACL = None

    INSTALLED_APPS += ["storages"]
    STORAGES = {
        "default": {"BACKEND": "core.infrastructure.storage.storages.MediaS3Storage"},
        "staticfiles": {"BACKEND": "core.infrastructure.storage.storages.StaticS3Storage"},
    }
    STATIC_URL = f"{MINIO_ENDPOINT.rstrip('/')}/{MINIO_BUCKET}/static/"
    MEDIA_URL = f"{MINIO_ENDPOINT.rstrip('/')}/{MINIO_BUCKET}/media/"
else:
    MEDIA_ROOT = str(BASE_DIR / "media")
    MEDIA_URL = "/media/"
    STATIC_URL = "/static/"

# EMAIL
# ------------------------------------------------------------------------------
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="LabMango <noreply@labmango.local>")
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = env("DJANGO_EMAIL_SUBJECT_PREFIX", default="[LabMango]")

# SENTRY  (enabled in module phase)
# ------------------------------------------------------------------------------
# TODO (infra-sentry): Configure Sentry SDK integration here

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
        "request_id": {"()": "core.common.logging.RequestIdFilter"},
    },
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s [%(request_id)s] %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django.request": {
            "handlers": ["mail_admins"],
            "level": "ERROR",
            "propagate": True,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console", "mail_admins"],
            "propagate": True,
        },
    },
}