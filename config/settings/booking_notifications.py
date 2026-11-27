"""Fail-closed notification configuration. Never include endpoint values in errors."""

from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured


def notification_settings(env) -> dict:
    enabled = env.bool("BOOKING_NOTIFICATIONS_ENABLED", default=False)
    email = env.bool("BOOKING_NOTIFICATIONS_EMAIL_ENABLED", default=False)
    teams = env.bool("BOOKING_NOTIFICATIONS_TEAMS_ENABLED", default=False)
    # Web (bell, toast, opt-in desktop notification) for the start and inactivity reminders.
    in_app = env.bool("BOOKING_NOTIFICATIONS_IN_APP_ENABLED", default=False)
    raw_cutoff = env("BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF", default="")
    cutoff = None
    if raw_cutoff:
        try:
            cutoff = datetime.fromisoformat(raw_cutoff.replace("Z", "+00:00"))
        except ValueError:
            raise ImproperlyConfigured("Booking notification cutoff must be a UTC timestamp.") from None
        offset = cutoff.utcoffset()
        if cutoff.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ImproperlyConfigured("Booking notification cutoff must be a UTC timestamp.")
        cutoff = cutoff.astimezone(timezone.utc)
    endpoint = env("BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL", default="")
    # Dedicated administrative endpoint only; user input cannot select a destination URL.
    hosts = env.list("BOOKING_NOTIFICATIONS_TEAMS_ALLOWED_HOSTS", default=[])
    raw_tenant = env("BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID", default="")
    tenant = None
    if raw_tenant:
        try:
            tenant = UUID(raw_tenant)
        except ValueError:
            raise ImproperlyConfigured("Teams expected tenant must be a UUID.") from None
    if enabled and cutoff is None:
        raise ImproperlyConfigured("Enabled booking notifications require a UTC enablement cutoff.")
    if enabled and teams:
        try:
            url = urlsplit(endpoint)
            valid = url.scheme == "https" and url.hostname in hosts and url.port in (None, 443)
            valid = valid and not url.username and not url.password and not url.fragment
            host = url.hostname or ""
            if "%" in host:
                valid = False
            try:
                address = ip_address(host)
            except ValueError:
                pass  # DNS and rebinding remain an operator egress-policy gate.
            else:
                valid = valid and address.is_global
                mapped = getattr(address, "ipv4_mapped", None)
                if mapped is not None:
                    valid = valid and mapped.is_global
        except ValueError:
            valid = False
        if not valid:
            raise ImproperlyConfigured("Teams workflow requires HTTPS and an explicitly allowed host.")
        if tenant is None:
            raise ImproperlyConfigured("Enabled Teams notifications require an expected tenant UUID.")
    return {
        "BOOKING_NOTIFICATIONS_ENABLED": enabled,
        "BOOKING_NOTIFICATIONS_EMAIL_ENABLED": email,
        "BOOKING_NOTIFICATIONS_TEAMS_ENABLED": teams,
        "BOOKING_NOTIFICATIONS_IN_APP_ENABLED": in_app,
        "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": cutoff,
        "BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL": endpoint,
        "BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID": tenant,
        "BOOKING_NOTIFICATIONS_QUEUE": env("BOOKING_NOTIFICATIONS_QUEUE", default="booking_notifications"),
        **slot_watch_settings(env),
    }


def slot_watch_settings(env) -> dict:
    """Bench slot watches. Web delivery needs only this flag; email and Teams also need the
    booking notification master switch and their channel switch (validated above)."""
    try:
        lead = int(env("BOOKING_SLOT_WATCH_LEAD_MINUTES", default="15"))
    except (TypeError, ValueError):
        raise ImproperlyConfigured("Slot watch lead time must be a whole number of minutes.") from None
    if not 1 <= lead <= 120:
        raise ImproperlyConfigured("Slot watch lead time must be between 1 and 120 minutes.")
    app_url = str(env("BOOKING_SLOT_WATCH_APP_URL", default="") or "").strip().rstrip("/")
    if app_url:
        parts = urlsplit(app_url)
        if parts.scheme not in ("https", "http") or not parts.hostname or parts.query or parts.fragment:
            raise ImproperlyConfigured("Slot watch app URL must be the Lab Mango web address, e.g. https://host.")
    return {
        # On by default: web alerts need nothing else. Email and Teams keep their own switches.
        "BOOKING_SLOT_WATCH_ENABLED": env.bool("BOOKING_SLOT_WATCH_ENABLED", default=True),
        "BOOKING_SLOT_WATCH_LEAD_MINUTES": lead,
        # Public web address of the frontend, used for "Book now" links in email and Teams.
        "BOOKING_SLOT_WATCH_APP_URL": app_url,
    }
