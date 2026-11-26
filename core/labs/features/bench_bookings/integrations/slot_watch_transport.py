"""Slot watch messages over email, Teams (private chat workflow) and the web notification feed.

Same sanitization rules as booking notifications: never log URLs, recipients, bodies or raw errors.
"""

from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from core.common.notifications import DeliveryOutcome
from core.infrastructure.email.service import send_email
from core.infrastructure.teams.service import TeamsProxyPolicy, post_teams_json
from core.users.public import VerifiedTeamsRecipient

from .notification_transport import _teams_delivery_outcome, protect_workflow_logs, teams_notification_payload

HEADINGS = {
    "slot_ending_soon": "A bench you are watching frees up soon",
    "slot_freed": "A bench you are watching is now free",
}


def _local(value: str) -> datetime:
    return timezone.localtime(datetime.fromisoformat(value))


def message_context(*, kind: str, snapshot: dict) -> dict:
    return {
        "heading": HEADINGS[kind],
        "bench_name": snapshot.get("bench_name") or "Bench",
        "free_from": _local(snapshot["free_from"]),
        "free_until": _local(snapshot["free_until"]),
        "range_start": _local(snapshot["range_start"]),
        "range_end": _local(snapshot["range_end"]),
        "time_zone": settings.TIME_ZONE,
        "booking_url": getattr(settings, "BOOKING_SLOT_WATCH_BOOKING_URL", ""),
    }


def slot_text(*, kind: str, snapshot: dict) -> str:
    return render_to_string(
        "labs/bench_bookings/slot_watch.txt", message_context(kind=kind, snapshot=snapshot)
    ).strip()


def web_message(*, kind: str, snapshot: dict) -> tuple[str, str]:
    """(message, details) for the persisted web notification; both fit 255 characters."""
    context = message_context(kind=kind, snapshot=snapshot)
    message = f"{context['heading']}: {context['bench_name']}"[:255]
    details = (
        f"Free {context['free_from']:%Y-%m-%d %H:%M} – {context['free_until']:%H:%M} "
        f"({context['time_zone']}). Book it before someone else does."
    )[:255]
    return message, details


def web_expiry(*, snapshot: dict, now: datetime) -> datetime:
    return max(datetime.fromisoformat(snapshot["free_until"]), now + timedelta(minutes=15))


def send_slot_email(*, recipient: str, kind: str, snapshot: dict, event_id: UUID) -> DeliveryOutcome:
    context = message_context(kind=kind, snapshot=snapshot) | {"event_id": str(event_id)}
    sent = send_email(
        subject=f"Lab Mango: {context['heading']}",
        context=context,
        template="emails/slot_available.html",
        receivers=[recipient],
        log_failure_details=False,
    )
    return DeliveryOutcome("sent", "accepted") if sent else DeliveryOutcome("retry", "email_not_sent")


def send_slot_teams(
    *, kind: str, snapshot: dict, event_id: UUID, teams_recipient: VerifiedTeamsRecipient
) -> DeliveryOutcome:
    protect_workflow_logs()
    result = post_teams_json(
        getattr(settings, "BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL", ""),
        teams_notification_payload(
            event_id=event_id,
            text=slot_text(kind=kind, snapshot=snapshot),
            teams_recipient=teams_recipient,
        ),
        timeout=(3.0, 5.0),
        proxy_policy=TeamsProxyPolicy.DISABLED,
    )
    return _teams_delivery_outcome(result)
