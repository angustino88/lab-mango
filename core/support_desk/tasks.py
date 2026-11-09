"""Support Desk Celery tasks auto-discovery root."""

from core.support_desk.features.tickets.application.tasks import (
    auto_close_resolved_tickets,
    flag_sla_breaches,
    process_notification_outbox,
    scan_pending_attachments,
)

__all__ = [
    "auto_close_resolved_tickets",
    "flag_sla_breaches",
    "process_notification_outbox",
    "scan_pending_attachments",
]
