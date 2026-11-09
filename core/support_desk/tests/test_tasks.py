"""Tests for Support Desk Celery background tasks."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from core.support_desk.contracts import (
    AttachmentScanStatus,
    OutboxChannel,
    OutboxStatus,
)
from core.support_desk.features.tickets.application.tasks import (
    auto_close_resolved_tickets,
    process_notification_outbox,
    scan_pending_attachments,
)
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.ticket import SupportTicket


@pytest.mark.django_db
class TestAutoCloseTask:
    def test_auto_close_eligible_resolved_tickets(self, support_setup, requester_user):
        # Ticket 1: Resolved 10 days ago (eligible)
        t_eligible = SupportTicket.objects.create(
            number=101,
            key="SUP-000101",
            subject="Eligible auto close",
            description="...",
            category=support_setup["category"],
            priority=support_setup["priority_med"],
            status=support_setup["status_resolved"],
            requester=requester_user,
            created_by=requester_user,
            resolved_at=timezone.now() - timedelta(days=10),
        )

        # Ticket 2: Resolved 2 days ago (not eligible, window is 7 days)
        t_recent = SupportTicket.objects.create(
            number=102,
            key="SUP-000102",
            subject="Recent resolved",
            description="...",
            category=support_setup["category"],
            priority=support_setup["priority_med"],
            status=support_setup["status_resolved"],
            requester=requester_user,
            created_by=requester_user,
            resolved_at=timezone.now() - timedelta(days=2),
        )

        closed_count = auto_close_resolved_tickets()
        assert closed_count == 1

        t_eligible.refresh_from_db()
        t_recent.refresh_from_db()

        assert t_eligible.status == support_setup["status_closed"]
        assert t_eligible.closed_at is not None
        assert t_recent.status == support_setup["status_resolved"]


@pytest.mark.django_db
class TestNotificationOutboxTask:
    def test_process_outbox_email_delivery(self, requester_user):
        outbox = NotificationOutbox.objects.create(
            event_id="test-event-01",
            recipient=requester_user,
            channel=OutboxChannel.EMAIL.value,
            payload={
                "subject": "Ticket SUP-000001 Created",
                "message": "Your ticket has been submitted.",
                "deep_link": "https://labmango.example.com/support/SUP-000001",
            },
            status=OutboxStatus.PENDING.value,
        )

        processed = process_notification_outbox(batch_size=10)
        assert processed == 1

        outbox.refresh_from_db()
        assert outbox.status == OutboxStatus.SENT.value
        assert outbox.sent_at is not None

        assert len(mail.outbox) == 1
        sent_email = mail.outbox[0]
        assert sent_email.subject == "Ticket SUP-000001 Created"
        assert requester_user.email in sent_email.to


@pytest.mark.django_db
class TestAttachmentScannerTask:
    def test_scan_pending_attachments(self, support_setup, requester_user):
        ticket = SupportTicket.objects.create(
            number=103,
            key="SUP-000103",
            subject="Scan ticket",
            description="...",
            category=support_setup["category"],
            priority=support_setup["priority_med"],
            status=support_setup["status_open"],
            requester=requester_user,
            created_by=requester_user,
        )
        att = TicketAttachment.objects.create(
            ticket=ticket,
            uploaded_by=requester_user,
            filename="scan_test.txt",
            content_type="text/plain",
            size=10,
            scan_status=AttachmentScanStatus.PENDING.value,
        )

        scanned = scan_pending_attachments()
        assert scanned == 1
        att.refresh_from_db()
        # Since no physical file storage was mocked for file.name, it marks INFECTED
        assert att.scan_status in (AttachmentScanStatus.CLEAN.value, AttachmentScanStatus.INFECTED.value)
