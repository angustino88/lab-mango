"""No env imports, no DB connection, no broker or network for isolated notification checks."""

from pathlib import Path

SECRET_KEY = "synthetic-notification-test-key-not-for-deployment"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "core.common",
    "core.reference_data",
    "core.users",
    "core.labs",
    "django_celery_beat",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "notifications@example.invalid"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [Path(__file__).resolve().parents[1] / "core" / "templates"],
        "APP_DIRS": True,
    }
]
BOOKING_NOTIFICATIONS_ENABLED = False
BOOKING_NOTIFICATIONS_EMAIL_ENABLED = False
BOOKING_NOTIFICATIONS_TEAMS_ENABLED = False
BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF = None
BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL = "https://workflow.example.invalid/test"
BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID = None
BOOKING_NOTIFICATIONS_QUEUE = "booking_notifications"
