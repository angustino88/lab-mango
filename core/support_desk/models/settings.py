"""System-wide configuration settings for Support Desk."""

from django.conf import settings
from django.db import models

from core.support_desk.contracts import TICKET_TYPE_CHOICES, TicketType

DEFAULT_ALLOWED_EXTENSIONS = [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".txt",
    ".log",
    ".csv",
    ".json",
    ".zip",
    ".xml",
]


class SupportSettings(models.Model):
    """Admin-managed singleton configuration for Support Desk."""

    reopen_window_days = models.PositiveIntegerField(
        default=14,
        help_text="Days after resolution during which a requester may reopen a ticket.",
    )
    auto_close_days = models.PositiveIntegerField(
        default=0,
        help_text="Days after resolution before auto-closing a ticket (0 to disable).",
    )
    max_attachment_size_bytes = models.PositiveBigIntegerField(
        default=26214400,
        help_text="Maximum allowed attachment size in bytes (default 25 MB).",
    )
    allowed_attachment_extensions = models.JSONField(
        default=list,
        help_text="List of permitted file extensions with dots, e.g. ['.png', '.pdf'].",
    )
    max_attachments_per_ticket = models.PositiveIntegerField(
        default=10,
        help_text="Maximum number of attachments allowed on a single ticket.",
    )
    comment_edit_window_minutes = models.PositiveIntegerField(
        default=15,
        help_text="Minutes after creation during which an author may edit/delete their comment.",
    )
    requesters_can_set_priority = models.BooleanField(
        default=True,
        help_text="If disabled, requesters describe impact/urgency and the priority is derived (agents still set it).",
    )
    sla_enabled = models.BooleanField(
        default=True,
        help_text="Compute SLA deadlines and flag breaches from the priority targets.",
    )
    sla_at_risk_percent = models.PositiveSmallIntegerField(
        default=80,
        help_text="A ticket is 'at risk' once this percentage of its SLA window has elapsed.",
    )
    csat_enabled = models.BooleanField(
        default=True,
        help_text="Allow requesters to rate resolved tickets (1-5).",
    )
    csat_window_days = models.PositiveIntegerField(
        default=14,
        help_text="Days after resolution during which the requester can submit a satisfaction rating.",
    )
    default_ticket_type = models.CharField(
        max_length=20,
        choices=TICKET_TYPE_CHOICES,
        default=TicketType.INCIDENT.value,
        help_text="Type applied when a ticket is created without one.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "Support Desk Settings"
        verbose_name_plural = "Support Desk Settings"

    def __str__(self) -> str:
        return "Support Desk Configuration"

    @classmethod
    def get_solo(cls) -> "SupportSettings":
        """Get or initialize the singleton settings record."""
        config, created = cls.objects.get_or_create(
            id=1,
            defaults={
                "allowed_attachment_extensions": DEFAULT_ALLOWED_EXTENSIONS,
            },
        )
        if not config.allowed_attachment_extensions:
            config.allowed_attachment_extensions = DEFAULT_ALLOWED_EXTENSIONS
            config.save(update_fields=["allowed_attachment_extensions"])
        return config
