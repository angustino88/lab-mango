"""Notification utilities for storage quota alerts and calendar reminders."""
from __future__ import annotations

import logging
import smtplib
import uuid
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from core.infrastructure.email.service import send_email

logger = logging.getLogger(__name__)

_ALERT_DESCRIPTION = (
    "Your storage usage has exceeded the assigned quota. Please clean up your "
    "storage allocation to prevent service disruption."
)
_MAX_LINE_OCTETS = 75


def _fold_ical_line(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= _MAX_LINE_OCTETS:
        return line
    chunks, start = [], 0
    while start < len(encoded):
        limit = _MAX_LINE_OCTETS if start == 0 else _MAX_LINE_OCTETS - 1
        chunks.append(encoded[start : start + limit].decode("utf-8", errors="ignore"))
        start += limit
    return "\r\n ".join(chunks)


def generate_storage_quota_ical(username: str, email_domain: str) -> bytes:
    """Generate an iCalendar reminder event for storage quota remediation."""
    now = timezone.now()
    now_str = now.strftime("%Y%m%dT%H%M%SZ")
    deadline_str = (now + timedelta(days=7)).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Lab Mango//Storage Quota Remediation//EN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"DTSTART:{now_str}",
        f"DTEND:{deadline_str}",
        f"DTSTAMP:{now_str}",
        f"CREATED:{now_str}",
        f"UID:{uuid.uuid4()}@labmango",
        "SUMMARY:Storage Cleanup Required",
        f"DESCRIPTION:{_ALERT_DESCRIPTION}",
        f"ORGANIZER:mailto:{settings.DEFAULT_FROM_EMAIL}",
        f"ATTENDEE:mailto:{username}@{email_domain}",
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold_ical_line(ln) for ln in lines).encode("utf-8")


def send_storage_quota_user_email(username: str, quotas: list, email_domain: str) -> bool:
    """Dispatch storage quota warning email with attached iCalendar reminder."""
    try:
        html_content = render_to_string(
            "emails/user_exceed_quota.html",
            {"user": username, "quotas": quotas},
        )
        email = EmailMessage(
            subject="[Lab Mango] Storage Quota Exceeded",
            body=html_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[f"{username}@{email_domain}"],
        )
        email.content_subtype = "html"
        email.attach("reminder.ics", generate_storage_quota_ical(username, email_domain), "text/calendar")
        return bool(email.send(fail_silently=False))
    except (smtplib.SMTPException, ConnectionError, OSError) as exc:
        logger.error("Failed to send quota email to %s: %s", username, exc)
        return False


def send_storage_quota_management_email(exceeded_quotas: list, receivers: list[str]) -> bool:
    """Dispatch summary report of all quota violations to administrators."""
    if not receivers:
        return True

    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for q in exceeded_quotas:
        comp_id = getattr(q, "computer_identifier", "N/A")
        grouped[("Default Lab", comp_id)].append(q)

    return send_email(
        subject="[Lab Mango] Storage Quota Incident Summary",
        context={"quotas": grouped.items()},
        template="emails/manage_exceed_quota.html",
        receivers=receivers,
    )


__all__ = [
    "generate_storage_quota_ical",
    "send_storage_quota_management_email",
    "send_storage_quota_user_email",
]
