"""Transactional outbox model for reliable notifications."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.support_desk.contracts import OutboxChannel, OutboxStatus


class NotificationOutbox(models.Model):
    """Reliable outbox record for asynchronous notification dispatch."""

    event_id = models.CharField(max_length=64, db_index=True)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    channel = models.CharField(
        max_length=20,
        choices=[(c.value, c.name.title()) for c in OutboxChannel],
    )
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name.title()) for s in OutboxStatus],
        default=OutboxStatus.PENDING.value,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification Outbox Entry"
        verbose_name_plural = "Notification Outbox Entries"
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "recipient", "channel"],
                name="unique_outbox_event_recipient_channel",
            )
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="idx_outbox_status_attempt"),
        ]

    def __str__(self) -> str:
        return f"Outbox {self.channel} to user {self.recipient_id} [{self.status}]"
