from .base import *  # noqa
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
DEBUG = env.bool("DJANGO_DEBUG", default=True)
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="!!!SET-DJANGO-SECRET-KEY-IN-ENV!!!-local-dev-only-not-for-production",
)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:3000"],
)

# CACHES
# ------------------------------------------------------------------------------
# Single-process development does not require a Redis service. Multi-worker local
# setups can opt into shared throttling with LOCAL_USE_REDIS_CACHE=True.
if env.bool("LOCAL_USE_REDIS_CACHE", default=False):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": env("CACHE_URL", default="redis://localhost:6379/1"),
            "OPTIONS": {
                "SOCKET_CONNECT_TIMEOUT": 3,
                "SOCKET_TIMEOUT": 3,
                "IGNORE_EXCEPTIONS": False,
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "labmango-local",
        }
    }

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

# MQTT (stub — integration in module phase)
# ------------------------------------------------------------------------------
MQTT_HOST = env.str("MQTT_HOST", default="localhost")
MQTT_PORT = env.int("MQTT_PORT", default=1883)
MQTT_USER = env.str("MQTT_USER", default="")
MQTT_PASSWORD = env.str("MQTT_PASSWORD", default="")
MQTT_PUBLISH = env.bool("MQTT_PUBLISH", default=False)
MQTT_PUB_TOPIC_PREFIX = env.str("MQTT_PUB_TOPIC", default="equipment")
MQTT_SUB_TOPIC = env.str("MQTT_SUB_TOPIC", default="broker/message")

# PROXIES (Bosch network)
# ------------------------------------------------------------------------------
HTTP_PROXY = env.str("HTTP_PROXY", default="")
HTTPS_PROXY = env.str("HTTPS_PROXY", default="")

# CORS
# ------------------------------------------------------------------------------
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True  # needed for HttpOnly cookie refresh token

# REFRESH TOKEN COOKIE — not secure in local dev (no HTTPS)
REFRESH_TOKEN_COOKIE_SECURE = False
REFRESH_TOKEN_COOKIE_SAMESITE = "Lax"

# DJANGO-DEBUG-TOOLBAR
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["debug_toolbar"]
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
if env("USE_DOCKER", default="no") == "yes":
    import socket

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS += [".".join(ip.split(".")[:-1] + ["1"]) for ip in ips]

# DJANGO-EXTENSIONS
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["django_extensions"]

# CELERY (dev: eager optional)
# ------------------------------------------------------------------------------
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_ALWAYS_EAGER = False

# MINIO / S3 STORAGE
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
