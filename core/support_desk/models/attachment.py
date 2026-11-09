"""Support ticket attachment model."""

from django.conf import settings
from django.db import models

from core.support_desk.contracts import AttachmentScanStatus


class TicketAttachment(models.Model):
    """File attachment linked to a ticket or a comment."""

    ticket = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    comment = models.ForeignKey(
        "support_desk.TicketComment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_attachments",
    )
    storage_key = models.CharField(max_length=255, unique=True)
    file = models.FileField(upload_to="support_desk/attachments/%Y/%m/%d/", max_length=500, blank=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    scan_status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name.title()) for s in AttachmentScanStatus],
        default=AttachmentScanStatus.CLEAN.value,
    )
    is_restricted = models.BooleanField(
        default=False,
        help_text="Restricted attachments are visible only to support agents and administrators.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Ticket Attachment"
        verbose_name_plural = "Ticket Attachments"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["ticket", "created_at"], name="idx_att_ticket_created"),
        ]

    def __str__(self) -> str:
        return f"{self.filename} ({self.size} bytes) on {self.ticket.key}"
