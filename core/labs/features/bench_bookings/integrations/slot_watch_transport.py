"""Slot watch messages over email, Teams (private chat workflow) and the web notification feed.

Every message leads with the outcome ("Bench 07 is available from 14:00"), gives the free window, and
offers one action: book that slot, opened in Lab Mango with bench and times prefilled.

Same sanitization rules as booking notifications: never log URLs, recipients, bodies or raw errors.
"""

from datetime import datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from core.common.notifications import DeliveryOutcome
from core.infrastructure.email.service import send_email
from core.infrastructure.teams.service import TeamsProxyPolicy, post_teams_json
from core.users.public import VerifiedTeamsRecipient

from .notification_transport import _teams_delivery_outcome, protect_workflow_logs, teams_notification_payload

# The booking form opens with this much time selected; users adjust before booking.
SUGGESTED_BOOKING = timedelta(hours=2)

ENDING_SOON_KINDS = frozenset({"slot_ending_soon", "booking_ending_soon"})

INTROS = {
    "slot_ending_soon": "A booking in the time you're watching is about to end.",
    "slot_freed": "A booking in the time you're watching was cancelled or finished early.",
    "booking_ending_soon": "The booking you're following is about to end.",
    "booking_released": "The booking you're following has ended.",
}


def _local(value: str) -> datetime:
    return timezone.localtime(datetime.fromisoformat(value))


def _day(value: datetime, now: datetime) -> str:
    delta = (value.date() - timezone.localtime(now).date()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return f"{value:%a %d %b}"


def describe_window(free_from: datetime, free_until: datetime | None, now: datetime) -> str:
    """ "Today 14:00 – 16:00", "Tomorrow from 09:30", "Thu 27 Nov 22:00 – Fri 28 Nov 02:00"."""
    start = f"{_day(free_from, now)} {free_from:%H:%M}"
    if free_until is None:
        return f"{_day(free_from, now)} from {free_from:%H:%M}"
    if free_until.date() == free_from.date():
        return f"{start} – {free_until:%H:%M}"
    return f"{start} – {_day(free_until, now)} {free_until:%H:%M}"


def booking_path(*, snapshot: dict, now: datetime) -> str:
    """In-app link that opens the booking form for this bench and free time."""
    free_from = max(datetime.fromisoformat(snapshot["free_from"]), now)
    ends = free_from + SUGGESTED_BOOKING
    if snapshot.get("free_until"):
        ends = min(ends, datetime.fromisoformat(snapshot["free_until"]))
    if not snapshot.get("is_follow") and snapshot.get("range_end"):
        ends = min(ends, datetime.fromisoformat(snapshot["range_end"]))
    if ends <= free_from:
        ends = free_from + timedelta(minutes=30)
    query = urlencode(
        {
            "action": "create",
            "bench_ids": snapshot["bench_id"],
            "starts_at": free_from.replace(second=0, microsecond=0).isoformat(),
            "ends_at": ends.replace(second=0, microsecond=0).isoformat(),
        }
    )
    return f"/booking-calendar?{query}"


def message_context(*, kind: str, snapshot: dict, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    bench = snapshot.get("bench_name") or "The bench"
    free_from = _local(snapshot["free_from"])
    free_until = _local(snapshot["free_until"]) if snapshot.get("free_until") else None
    if kind in ENDING_SOON_KINDS and free_from > now:
        title = f"{bench} frees up at {free_from:%H:%M}"
    else:
        title = f"{bench} is available now" if free_from <= now + timedelta(minutes=1) else f"{bench} is available"
    app_url = getattr(settings, "BOOKING_SLOT_WATCH_APP_URL", "")
    path = booking_path(snapshot=snapshot, now=now)
    is_follow = bool(snapshot.get("is_follow"))
    return {
        "title": title,
        "intro": INTROS[kind],
        "bench_name": bench,
        "window": describe_window(free_from, free_until, now),
        "time_zone": settings.TIME_ZONE,
        "is_follow": is_follow,
        "watched": (
            None if is_follow else describe_window(_local(snapshot["range_start"]), _local(snapshot["range_end"]), now)
        ),
        "action_path": path,
        "booking_url": f"{app_url}{path}" if app_url else "",
        "alerts_url": f"{app_url}/dashboard" if app_url else "",
    }


def slot_text(*, kind: str, snapshot: dict) -> str:
    return render_to_string(
        "labs/bench_bookings/slot_watch.txt", message_context(kind=kind, snapshot=snapshot)
    ).strip()


def web_message(*, kind: str, snapshot: dict) -> tuple[str, str, str]:
    """(title, details, action_path) for the web notification; text fits the 255-character fields."""
    context = message_context(kind=kind, snapshot=snapshot)
    details = f"Available {context['window']}. Not reserved for you — book now to secure it."
    return context["title"][:255], details[:255], context["action_path"]


def web_expiry(*, snapshot: dict, now: datetime) -> datetime:
    if not snapshot.get("free_until"):
        return now + timedelta(hours=2)
    return max(datetime.fromisoformat(snapshot["free_until"]), now + timedelta(minutes=15))


def send_slot_email(*, recipient: str, kind: str, snapshot: dict, event_id: UUID) -> DeliveryOutcome:
    context = message_context(kind=kind, snapshot=snapshot) | {"event_id": str(event_id)}
    sent = send_email(
        subject=f"{context['title']} · Lab Mango",
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
