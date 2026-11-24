"""Support ticket work log (effort tracking) model."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

MIN_WORK_LOG_MINUTES = 1
MAX_WORK_LOG_MINUTES = 14400  # 240 hours (10 full days) per single entry


class TicketWorkLog(models.Model):
    """Time / effort entry logged by a requester or support agent on a ticket."""

    ticket = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="work_logs",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_work_logs",
    )
    time_spent_minutes = models.PositiveIntegerField(
        validators=[
            MinValueValidator(MIN_WORK_LOG_MINUTES),
            MaxValueValidator(MAX_WORK_LOG_MINUTES),
        ],
        help_text="Effort spent in whole minutes (1 to 14,400).",
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="When the work was started or performed.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional summary of the work performed.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Ticket Work Log"
        verbose_name_plural = "Ticket Work Logs"
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["ticket", "-started_at", "-id"], name="idx_work_log_ticket_started"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(time_spent_minutes__gte=MIN_WORK_LOG_MINUTES)
                & Q(time_spent_minutes__lte=MAX_WORK_LOG_MINUTES),
                name="work_log_minutes_range",
            ),
        ]

    @property
    def etag(self) -> str:
        return f'"work-log-{self.pk}-v{self.version}"'

    def __str__(self) -> str:
        return f"WorkLog {self.id} ({self.time_spent_minutes}m) on {self.ticket.key}"


class TicketWorkLogCreateReceipt(models.Model):
    """Original response for a keyed work-log creation."""

    ticket = models.ForeignKey("support_desk.SupportTicket", on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    response_body = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "key"], name="work_log_create_replay_scope"),
        ]
