"""
Base settings — shared across all environments.
"""

from datetime import timedelta
from pathlib import Path

import environ

from config.openapi import ENUM_NAME_OVERRIDES

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# core/
APPS_DIR = BASE_DIR / "core"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=True)
if READ_DOT_ENV_FILE:
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
DEBUG = env.bool("DJANGO_DEBUG", False)
TIME_ZONE = "Asia/Ho_Chi_Minh"
LANGUAGE_CODE = "en-us"
SITE_ID = 1
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [str(BASE_DIR / "locale")]

DATABASES = {
    "default": env.db("DATABASE_URL"),
}
if "PROD_DATABASE_URL" in env and env("PROD_DATABASE_URL"):
    DATABASES["prod"] = env.db("PROD_DATABASE_URL")
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "config.admin_site.LabMangoAdminConfig",  # django.contrib.admin with the Lab Mango site
    "django.forms",
]
THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "django_celery_beat",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "rest_framework_api_key",
]
LOCAL_APPS = [
    "core.users",
    "core.common",
    "core.reference_data.apps.ReferenceDataConfig",
    "core.labs",
    "core.websocket",
    "core.support_desk",
    "core.agents",
    "core.routing",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# TODO (users module): Re-enable custom sites migrations once the module is migrated.
# MIGRATION_MODULES = {"sites": "core.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# LDAP (Bosch corporate directory)
# ------------------------------------------------------------------------------
LDAP_AUTH_URL = env("LDAP_AUTH_URL", default="ldaps://de.bosch.com:3269")
LDAP_AUTH_SEARCH_BASE = env("LDAP_AUTH_SEARCH_BASE", default="dc=bosch,dc=com")
LDAP_AUTH_WHITELIST = env.list("LDAP_AUTH_WHITELIST", default=["admin", "adminlab"])
ENTRA_SSO_ONLY = False  # Production overrides this unconditionally.
LDAP_AUTH_CONNECT_TIMEOUT = 5
LDAP_AUTH_RECEIVE_TIMEOUT = 10
LDAP_AUTH_CA_CERT_FILE = env("LDAP_AUTH_CA_CERT_FILE", default=None)

# AZURE AD / SSO
# ------------------------------------------------------------------------------
AAD_AUDIENCE = env("AAD_AUDIENCE", default="eb57f92a-fe50-46b7-b0d8-775cb6b9bdc6")
AAD_JWKS_URL = env(
    "AAD_JWKS_URL",
    default="https://login.microsoftonline.com/0ae51e19-07c8-4e4b-bb6d-648ee58410f4/discovery/v2.0/keys",
)
AAD_TENANT_ID = env("AAD_TENANT_ID", default="0ae51e19-07c8-4e4b-bb6d-648ee58410f4")
AAD_ISSUER = f"https://login.microsoftonline.com/{AAD_TENANT_ID}/v2.0"
# Entra login replay protection: the browser sends SHA-256(secret) as the nonce to Microsoft and the
# secret to /api/aad-login. ID tokens older than this are refused; each nonce is accepted once.
ENTRA_LOGIN_MAX_TOKEN_AGE = timedelta(minutes=10)
# First login only: bind an unbound Entra object ID to the existing non-privileged user whose username
# matches preferred_username (full UPN or local part). Never creates users.
ENTRA_BIND_BY_USERNAME = env.bool("ENTRA_BIND_BY_USERNAME", default=True)
# Safeguards for that first-login binding (owner decision 2026-11-12, option A):
# only these UPN domains are accepted; guests (#EXT# UPNs, acct=1) never are; an account that was ever
# bound before is never re-bound automatically. Binding an account older than the warning age is logged
# as a warning for review.
ENTRA_BIND_ALLOWED_DOMAINS = [
    domain.strip().lower()
    for domain in env.list("ENTRA_BIND_ALLOWED_DOMAINS", default=[env("EMAIL_USER_DOMAIN", default="bosch.com")])
    if domain.strip()
]
ENTRA_BIND_DORMANT_WARNING_DAYS = env.int("ENTRA_BIND_DORMANT_WARNING_DAYS", default=180)
ENTRA_FRONTEND_LOGIN_URL = env("ENTRA_FRONTEND_LOGIN_URL", default="/")

AUTH_USER_MODEL = "users.User"
BACKEND_ID = env("BACKEND_ID", default="dept_a")
# Signed agent requests: accepted clock skew; nonces are remembered for twice this window.
AGENT_REQUEST_MAX_SKEW_S = env.int("AGENT_REQUEST_MAX_SKEW_S", default=300)
ROUTING_SYNC_AUDIENCE = env("ROUTING_SYNC_AUDIENCE", default=f"api://labmango-{BACKEND_ID}")
ROUTING_SYNC_REQUIRED_ROLE = env("ROUTING_SYNC_REQUIRED_ROLE", default="Routing.Sync.Read")
ROUTING_SYNC_ENTRA_TENANT_IDS = env.list("ROUTING_SYNC_ENTRA_TENANT_IDS", default=[AAD_TENANT_ID])
ROUTING_SYNC_JWKS_URL = env("ROUTING_SYNC_JWKS_URL", default=AAD_JWKS_URL)
ROUTING_SYNC_STATIC_TOKEN_HASHES = env.list("ROUTING_SYNC_STATIC_TOKEN_HASHES", default=[])
ROUTING_SYNC_ENABLED_ENTITIES = ("users", "agents")
ROUTING_SYNC_SNAPSHOT_MAX_LIMIT = 5000
ROUTING_SYNC_CHANGES_MAX_LIMIT = 2000
ROUTING_SYNC_LONGPOLL_MAX_WAIT_S = 30
# Held long-polls re-read the stream head at this interval to see commits from other processes.
ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S = env.float("ROUTING_SYNC_LONGPOLL_POLL_INTERVAL_S", default=1.0)
LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
STATIC_ROOT = str(BASE_DIR / "staticfiles")
STATIC_URL = "/static/"
STATICFILES_DIRS = [str(APPS_DIR / "static")]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
MEDIA_ROOT = str(APPS_DIR / "media")
MEDIA_URL = "/media/"

# STORAGES  (Django 5.0+: replaces STATICFILES_STORAGE / DEFAULT_FILE_STORAGE)
# ------------------------------------------------------------------------------
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(APPS_DIR / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# FIXTURES
# ------------------------------------------------------------------------------
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_TIMEOUT = 5
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@bosch.com")
EMAIL_USER_DOMAIN = env("EMAIL_USER_DOMAIN", default="bosch.com")

# PROXY (used for MS Teams Power Automate webhooks)
# ------------------------------------------------------------------------------
HTTP_PROXY = env("HTTP_PROXY", default="")
HTTPS_PROXY = env("HTTPS_PROXY", default="")

# OTP / POWER AUTOMATE WEBHOOKS
# ------------------------------------------------------------------------------
OTP_PA_API = env("OTP_PA_API", default="")
MONITORING_PA_API = env("MONITORING_PA_API", default="")
BOOKING_PA_API = env("BOOKING_PA_API", default="")
EQUIPMENT_PA_API = env("EQUIPMENT_PA_API", default="")
BOOKING_APPROVAL_PA_API = env("BOOKING_APPROVAL_PA_API", default="")

# URS GROUP SYNC
# Labs roles are mapped per URS group in Django admin (URSGroup.labs_role); see
# core/users/access.py. Superusers are always treated as admin.
# ------------------------------------------------------------------------------
URS_API_URL = env("URS_API_URL", default="https://rb-pandora-n1.bosch.com:15000/service/info")
URS_API_VERIFY_SSL = env.bool("URS_API_VERIFY_SSL", default=False)
# Service token sent to the URS API. Empty by default: sync fails closed when unset.
URS_ACCESS_TOKEN = env("URS_ACCESS_TOKEN", default="")
URS_API_TIMEOUT_S = env.int("URS_API_TIMEOUT_S", default=15)
# URS is the source of truth and every sync applies all changes at once (owner decision 2026-11-12).
# Optional safety check, off by default: when on, a group sync that removes every member, or more than
# URS_SYNC_MAX_REMOVAL_RATIO of a group with at least URS_SYNC_BRAKE_MIN_MEMBERS members, is blocked
# until an operator forces it in Django admin.
URS_SYNC_SAFETY_BRAKE = env.bool("URS_SYNC_SAFETY_BRAKE", default=False)
URS_SYNC_MAX_REMOVAL_RATIO = env.float("URS_SYNC_MAX_REMOVAL_RATIO", default=0.5)
URS_SYNC_BRAKE_MIN_MEMBERS = env.int("URS_SYNC_BRAKE_MIN_MEMBERS", default=10)

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = "admin/"
ADMINS = []
MANAGERS = ADMINS
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

# CELERY
# ------------------------------------------------------------------------------
if USE_TZ:
    CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_RESULT_EXTENDED = True
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 5 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 4 * 60
CELERY_TASK_DEFAULT_QUEUE = env("CELERY_TASK_DEFAULT_QUEUE", default="labmango_backend")
CELERY_TASK_DEFAULT_EXCHANGE = env("CELERY_TASK_DEFAULT_EXCHANGE", default="labmango_backend")
CELERY_TASK_DEFAULT_ROUTING_KEY = env("CELERY_TASK_DEFAULT_ROUTING_KEY", default="labmango_backend")
CELERY_BEAT_SCHEDULER = env(
    "CELERY_BEAT_SCHEDULER",
    default="django_celery_beat.schedulers:DatabaseScheduler",
)
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
# Required in Celery 5.4+ to suppress deprecation warning
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# CELERY BEAT SCHEDULE
# ------------------------------------------------------------------------------
# Periodic work runs through django-celery-beat's database scheduler.
# Entries below are code-owned: the scheduler copies them into Periodic Tasks every time beat
# starts, so they exist in every environment without a manual step. An admin may still disable one
# in Django admin; beat keeps it disabled. Other schedules are defined as Periodic Tasks in Django
# admin (Django Celery Beat > Periodic tasks).
# Computing heartbeat timeout: task ``labs.equipment.computing.mark_stale_activities_offline``,
# crontab ``*/10 * * * *``.
CELERY_BEAT_SCHEDULE = {
    # Expire reservations nobody checked in to and complete bookings whose end time has passed
    # (owner decision O26). Idempotent and batched, safe to run every minute.
    "bench-booking-status-reconciliation": {
        "task": "labs.bench_bookings.reconcile_statuses",
        "schedule": env.float("BENCH_BOOKING_RECONCILE_INTERVAL_SECONDS", default=60.0),
    },
}

# DJANGO-ALLAUTH
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# allauth 0.65+ new-style config
ACCOUNT_LOGIN_METHODS = {"username"}  # replaces ACCOUNT_AUTHENTICATION_METHOD
ACCOUNT_SIGNUP_FIELDS = ["username*", "email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_ADAPTER = "core.users.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "core.users.adapters.SocialAccountAdapter"

# DJANGO REST FRAMEWORK
# ------------------------------------------------------------------------------
# API keys (djangorestframework-api-key): one switch for every API-key path. Keys stay valid while off;
# requests that rely only on a key are rejected (core.common.api.permissions.HasAPIKeyAccess).
API_KEY_ACCESS_ENABLED = env.bool("API_KEY_ACCESS_ENABLED", default=True)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "EXCEPTION_HANDLER": "core.common.api.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "config.schema.ProjectAutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    # Scoped throttles for public auth endpoints (see ScopedRateThrottle on each view).
    # Counters live in the default cache (Redis in production, shared across workers).
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="60/min"),
        "user": env("THROTTLE_USER", default="300/min"),
        "auth_login": env("THROTTLE_AUTH_LOGIN", default="10/min"),
        "auth_otp": env("THROTTLE_AUTH_OTP", default="5/min"),
        "auth_refresh": env("THROTTLE_AUTH_REFRESH", default="30/min"),
    },
}

CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOW_CREDENTIALS = True

# SIMPLE JWT
# ------------------------------------------------------------------------------
# Refresh token is stored in an HttpOnly cookie — never in JS-accessible storage.
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
REFRESH_TOKEN_COOKIE_SAMESITE = "Lax"
REFRESH_TOKEN_COOKIE_SECURE = env.bool("REFRESH_TOKEN_COOKIE_SECURE", default=True)  # False in local dev
REFRESH_TOKEN_COOKIE_HTTPONLY = True

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# DRF SPECTACULAR
# ------------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "LabMango API",
    "DESCRIPTION": "LabMango Backend REST API",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
    "ENUM_NAME_OVERRIDES": ENUM_NAME_OVERRIDES,
    "SERVERS": [
        {"url": "", "description": "Local Development Server"},
    ],
}

# LABS ANALYTICS
# ------------------------------------------------------------------------------
from datetime import datetime  # noqa: E402
from datetime import timezone as _tz  # noqa: E402

LAB_ANALYTICS_BASELINE = datetime(2025, 1, 1, tzinfo=_tz.utc)

from .booking_notifications import notification_settings  # noqa: E402

globals().update(notification_settings(env))
