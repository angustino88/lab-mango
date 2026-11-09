"""Sanitized transport outcomes. Never log exception text, URLs, recipients or bodies."""

import logging
from uuid import UUID

from django.conf import settings
from django.template.loader import render_to_string

from core.common.notifications import DeliveryOutcome, NotificationChannel
from core.infrastructure.email.service import send_email
from core.infrastructure.teams.service import TeamsPostCode, TeamsProxyPolicy, post_teams_json
from core.users.public import VerifiedTeamsRecipient

from ..contracts import BookingNotificationSnapshot

__all__ = [
    "DeliveryOutcome",
    "deliver",
    "notification_email_context",
    "notification_text",
    "teams_notification_payload",
]


class WorkflowLogFilter(logging.Filter):
    """Permanent, stateless suppression: never format or inspect a potentially secret URL."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Connectionpool DEBUG includes request targets; suppress all its messages.
        return False


_WORKFLOW_LOG_FILTER = WorkflowLogFilter()


def protect_workflow_logs() -> None:
    for name in ("urllib3.connectionpool", "requests.packages.urllib3.connectionpool"):
        logger = logging.getLogger(name)
        if _WORKFLOW_LOG_FILTER not in logger.filters:
            logger.addFilter(_WORKFLOW_LOG_FILTER)


def notification_text(*, kind: str, snapshot: BookingNotificationSnapshot) -> str:
    labels = {
        "created": "Booking created",
        "updated": "Booking materially updated",
        "start": "Scheduled booking time has arrived",
        "inactive": "Equipment inactivity reminder (over 60 minutes)",
    }
    return render_to_string(
        "labs/bench_bookings/notification.txt",
        {
            "heading": labels[kind],
            "snapshot": snapshot,
        },
    ).strip()


def teams_notification_payload(
    *,
    event_id: UUID,
    text: str,
    teams_recipient: VerifiedTeamsRecipient,
) -> dict[str, str]:
    """Return the private-recipient JSON body expected by the Teams workflow."""
    return {
        "event_id": str(event_id),
        "recipient_tenant_id": str(teams_recipient.tenant_id),
        "recipient_object_id": str(teams_recipient.object_id),
        "text": text,
    }


def notification_email_context(*, kind: str, snapshot: BookingNotificationSnapshot, event_id: UUID) -> dict:
    """Build an allowlisted, factual snapshot context for the existing HTML layout."""
    labels = {
        "created": "Booking created",
        "updated": "Booking materially updated",
        "start": "Scheduled booking time has arrived",
        "inactive": "Equipment inactivity reminder (over 60 minutes)",
    }
    action = kind if kind in {"created", "updated"} else "notification"
    return {
        "action": action,
        "snapshot": snapshot,
        "notification_heading": labels[kind],
        "event_id": str(event_id),
    }


def _teams_delivery_outcome(result) -> DeliveryOutcome:
    if result.sent:
        return DeliveryOutcome("sent", "accepted")
    if result.retryable:
        code = "network_transient" if result.code is TeamsPostCode.RETRYABLE_TRANSPORT else "http_transient"
        return DeliveryOutcome("retry", code)
    code = "transport_configuration" if result.code is TeamsPostCode.REQUEST_FAILED else "http_permanent"
    return DeliveryOutcome("failed", code)


def deliver(
    *,
    channel: str,
    recipient: str,
    event_id: UUID,
    kind: str,
    snapshot: BookingNotificationSnapshot,
    teams_recipient: VerifiedTeamsRecipient | None = None,
) -> DeliveryOutcome:
    text = notification_text(kind=kind, snapshot=snapshot)
    if channel == NotificationChannel.TEAMS.value:
        if teams_recipient is None:
            return DeliveryOutcome("skipped", "teams_identity_unavailable")
        protect_workflow_logs()
        # URL validation, recipient verification, and retries remain booking-owned.
        result = post_teams_json(
            settings.BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL,
            teams_notification_payload(
                event_id=event_id,
                text=text,
                teams_recipient=teams_recipient,
            ),
            timeout=(3.0, 5.0),
            proxy_policy=TeamsProxyPolicy.DISABLED,
        )
        return _teams_delivery_outcome(result)
    sent = send_email(
        subject="Lab Mango booking notification",
        context=notification_email_context(kind=kind, snapshot=snapshot, event_id=event_id),
        template="emails/booking_confirmation.html",
        receivers=[recipient],
        log_failure_details=False,
    )
    return DeliveryOutcome("sent", "accepted") if sent else DeliveryOutcome("retry", "email_not_sent")
