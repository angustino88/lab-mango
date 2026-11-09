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
        "BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF": cutoff,
        "BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL": endpoint,
        "BOOKING_NOTIFICATIONS_TEAMS_EXPECTED_TENANT_ID": tenant,
        "BOOKING_NOTIFICATIONS_QUEUE": env("BOOKING_NOTIFICATIONS_QUEUE", default="booking_notifications"),
    }
