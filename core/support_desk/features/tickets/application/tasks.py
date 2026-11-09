"""Celery tasks for Support Desk outbox processing, auto-closing, and security scans."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape, linebreaks

from config.celery_app import app as celery_app
from core.support_desk.contracts import (
    ActivityEventType,
    AttachmentScanStatus,
    OutboxChannel,
    OutboxStatus,
    SystemState,
)
from core.support_desk.features.tickets.application.attachment_scanner import get_scanner
from core.support_desk.features.tickets.application.notifications import queue_ticket_notifications
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.ticket import SupportTicket
from core.websocket.publish_service import publish_notification

logger = logging.getLogger(__name__)


OUTBOX_LEASE_SECONDS = 300


def _absolute_link(deep_link: str) -> str:
    base = (getattr(settings, "SUPPORT_DESK_BASE_URL", "") or "").rstrip("/")
    if deep_link.startswith("/") and base:
        return f"{base}{deep_link}"
    return deep_link


def _claim_outbox_batch(batch_size: int) -> list[int]:
    """Lease a batch of due rows so concurrent workers never dispatch the same notification twice.

    Rows are locked with ``SKIP LOCKED`` and pushed ``OUTBOX_LEASE_SECONDS`` into the future; if the worker dies
    mid-batch they simply become due again afterwards.
    """
    now = timezone.now()
    with transaction.atomic():
        ids = list(
            NotificationOutbox.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxStatus.PENDING.value, next_attempt_at__lte=now)
            .order_by("created_at")
            .values_list("pk", flat=True)[:batch_size]
        )
        if ids:
            NotificationOutbox.objects.filter(pk__in=ids).update(
                next_attempt_at=now + timedelta(seconds=OUTBOX_LEASE_SECONDS)
            )
    return ids


@celery_app.task(name="support_desk.process_notification_outbox")
def process_notification_outbox(batch_size: int = 50) -> int:
    """Dequeue pending notification outbox rows and dispatch via email and in-app websocket."""
    claimed_ids = _claim_outbox_batch(batch_size)
    records = NotificationOutbox.objects.select_related("recipient").filter(pk__in=claimed_ids).order_by("created_at")

    processed_count = 0
    for record in records:
        recipient = record.recipient
        payload = record.payload or {}
        channel = record.channel

        try:
            if channel == OutboxChannel.EMAIL.value:
                recipient_email = getattr(recipient, "email", None)
                if recipient_email and getattr(recipient, "is_active", True):
                    subject = payload.get("subject", "Support Desk Notification")
                    message = payload.get("message", "")
                    deep_link = _absolute_link(payload.get("deep_link", ""))

                    text_body = f"{message}\n\nView details: {deep_link}" if deep_link else message
                    html_body = linebreaks(escape(message))
                    if deep_link:
                        html_body += f'<p><a href="{escape(deep_link)}">View ticket in Lab Mango</a></p>'

                    email = EmailMultiAlternatives(
                        subject=subject,
                        body=text_body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[recipient_email],
                    )
                    email.attach_alternative(html_body, "text/html")
                    email.send(fail_silently=False)

            elif channel == OutboxChannel.IN_APP.value:
                publish_notification(
                    message=payload.get("message", "New support update"),
                    details=payload.get("ticket_key", ""),
                    target_user_id=recipient.pk if recipient else None,
                )

            record.status = OutboxStatus.SENT.value
            record.sent_at = timezone.now()
            record.error_message = ""
            record.save(update_fields=["status", "sent_at", "error_message"])
            processed_count += 1

        except Exception as exc:
            logger.exception("Failed to dispatch notification outbox record %s: %s", record.pk, exc)
            record.attempts += 1
            if record.attempts >= 5:
                record.status = OutboxStatus.FAILED.value
            else:
                backoff_seconds = (2 ** record.attempts) * 30
                record.next_attempt_at = timezone.now() + timedelta(seconds=backoff_seconds)
            record.error_message = str(exc)
            record.save(update_fields=["attempts", "status", "next_attempt_at", "error_message"])

    return processed_count


@celery_app.task(name="support_desk.auto_close_resolved_tickets")
def auto_close_resolved_tickets() -> int:
    """Auto-close tickets in Resolved system state exceeding the configured auto_close_days."""
    app_settings = SupportSettings.get_solo()
    if not app_settings.auto_close_days or app_settings.auto_close_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=app_settings.auto_close_days)
    closed_status = SupportStatus.objects.filter(is_final=True, is_active=True).order_by("sort_order", "id").first()
    if not closed_status:
        logger.warning("Auto-close skipped: no active status is flagged as final (is_final).")
        return 0

    eligible_tickets = (
        SupportTicket.objects.select_related("status", "category", "priority", "requester", "assignee")
        .filter(
            status__system_state=SystemState.DONE.value,
            resolved_at__lte=cutoff,
            closed_at__isnull=True,
        )
        .exclude(status=closed_status)
    )

    closed_count = 0
    for ticket in eligible_tickets:
        with transaction.atomic():
            old_status_name = ticket.status.name
            ticket.status = closed_status
            ticket.closed_at = timezone.now()
            ticket.sla_paused_at = None
            ticket.version += 1
            ticket.save(update_fields=["status", "closed_at", "sla_paused_at", "version"])

            TicketActivity.objects.create(
                ticket=ticket,
                event_type=ActivityEventType.STATUS_CHANGED.value,
                actor=None,
                actor_name="System",
                payload={
                    "from_status": old_status_name,
                    "to_status": closed_status.name,
                    "reason": f"Automatically closed after {app_settings.auto_close_days} days in resolved state.",
                },
            )

            queue_ticket_notifications(ticket, "status_changed", actor=None)
            closed_count += 1

    return closed_count


@celery_app.task(name="support_desk.scan_pending_attachments")
def scan_pending_attachments() -> int:
    """Scan quarantined attachments with the configured scanner and release the clean ones."""
    scanner = get_scanner()
    pending_attachments = TicketAttachment.objects.filter(
        scan_status=AttachmentScanStatus.PENDING.value,
        deleted_at__isnull=True,
    )
    scanned_count = 0
    for attachment in pending_attachments:
        try:
            result = scanner(attachment)
            attachment.scan_status = AttachmentScanStatus(result).value
            attachment.save(update_fields=["scan_status"])
            scanned_count += 1
        except Exception as exc:
            # Leave it quarantined (pending) so the next run retries; never fail open.
            logger.error("Scan failure on attachment %s: %s", attachment.pk, exc)

    return scanned_count


SLA_SCAN_BATCH = 500


@celery_app.task(name="support_desk.flag_sla_breaches")
def flag_sla_breaches() -> int:
    """Stamp and announce response / resolution SLA breaches on unfinished, un-paused tickets."""
    if not SupportSettings.get_solo().sla_enabled:
        return 0

    now = timezone.now()
    base = (
        SupportTicket.objects.select_related("status", "team", "team__lead", "assignee", "requester", "priority")
        .exclude(status__system_state=SystemState.DONE.value)
        .filter(sla_paused_at__isnull=True)
    )
    breached = 0
    windows = (
        ("response", "response_due_at", "response_breached_at", {"first_response_at__isnull": True}),
        ("resolution", "resolution_due_at", "resolution_breached_at", {}),
    )
    for kind, due_field, flag_field, extra_filter in windows:
        due_tickets = base.filter(
            **{f"{due_field}__lte": now, f"{flag_field}__isnull": True},
            **extra_filter,
        ).order_by(due_field)[:SLA_SCAN_BATCH]
        for ticket in due_tickets:
            with transaction.atomic():
                # Guard against two scanners racing: only the one that flips the flag announces it.
                flipped = SupportTicket.objects.filter(pk=ticket.pk, **{f"{flag_field}__isnull": True}).update(
                    **{flag_field: now}
                )
                if not flipped:
                    continue
                TicketActivity.objects.create(
                    ticket=ticket,
                    event_type=ActivityEventType.SLA_BREACHED.value,
                    actor=None,
                    actor_name="System",
                    payload={"sla": kind, "due_at": getattr(ticket, due_field).isoformat(), "priority": ticket.priority.name},
                )
                queue_ticket_notifications(ticket, "sla_breached", actor=None, extra={"sla_kind": kind})
                breached += 1
    return breached
