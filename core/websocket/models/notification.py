"""Notification model — persisted for hybrid reliability."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class Notification(TimeStampedModel, UserStampedModel):
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    ANNOUNCEMENT = "announcement"

    MESSAGE_TYPES = [
        (SUCCESS, _("Success")),
        (ERROR, _("Error")),
        (WARNING, _("Warning")),
        (INFO, _("Info")),
        (ANNOUNCEMENT, _("Announcement")),
    ]

    message = models.CharField(max_length=255, default="")
    details = models.CharField(max_length=255, default="", null=True, blank=True)
    message_type = models.CharField(
        max_length=255,
        default=INFO,
        choices=MESSAGE_TYPES,
    )
    expiry_date = models.DateTimeField()
    # Optional: target user for per-user notifications (null = broadcast)
    target_user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="targeted_notifications",
    )

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["expiry_date"]),
            models.Index(fields=["target_user", "created"]),
        ]

    def clean(self) -> None:
        super().clean()
        if self.expiry_date and self.expiry_date <= timezone.now():
            raise ValidationError({"expiry_date": _("Expiry date must be in the future.")})

    def __str__(self) -> str:
        return self.message
