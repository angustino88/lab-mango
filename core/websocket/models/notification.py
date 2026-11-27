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

    TONE_CHOICES = [
        (INFO, _("Info")),
        (WARNING, _("Warning")),
        (ERROR, _("Error")),
        (SUCCESS, _("Success")),
    ]

    ALERT = "alert"
    BANNER = "banner"

    DISPLAY_MODES = [
        (ALERT, _("One-time alert")),
        (BANNER, _("Expiring banner")),
    ]

    message = models.CharField(max_length=255, default="")
    details = models.CharField(max_length=255, default="", null=True, blank=True)
    message_type = models.CharField(
        max_length=255,
        default=INFO,
        choices=MESSAGE_TYPES,
    )
    display_mode = models.CharField(
        max_length=16,
        default=ALERT,
        choices=DISPLAY_MODES,
        help_text=_(
            "One-time alert pops up once and lives in the bell inbox; expiring banner stays pinned "
            "at the top until expiry or dismissal."
        ),
    )
    is_dismissible = models.BooleanField(
        default=True,
        help_text=_("Banners only: when unchecked, the banner stays pinned until expiry and cannot be dismissed."),
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text=_("When this notification was first broadcast over WebSocket."),
    )
    expiry_date = models.DateTimeField()
    # Optional in-app destination for the notification's primary action, e.g. "/booking-calendar?...".
    # Always a path inside this app (starts with "/"), never an external URL.
    action_path = models.CharField(max_length=500, blank=True, default="")
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
            models.Index(fields=["display_mode", "expiry_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action_path="")
                | (models.Q(action_path__startswith="/") & ~models.Q(action_path__startswith="//")),
                name="notification_action_path_internal",
            ),
            models.CheckConstraint(
                condition=models.Q(display_mode__in=("alert", "banner")),
                name="notification_display_mode_valid",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self._state.adding and self.expiry_date and self.expiry_date <= timezone.now():
            raise ValidationError({"expiry_date": _("Expiry date must be in the future.")})
        if self.action_path and (not self.action_path.startswith("/") or self.action_path.startswith("//")):
            raise ValidationError({"action_path": _("Must be a path inside the app.")})

    def __str__(self) -> str:
        return self.message


class BannerNotification(Notification):
    """Proxy model for Django Admin management of time-bounded expiring banners."""

    class Meta:
        proxy = True
        verbose_name = _("Expiring Banner")
        verbose_name_plural = _("Expiring Banners")


class AlertNotification(Notification):
    """Proxy model for Django Admin management of one-time alert notifications."""

    class Meta:
        proxy = True
        verbose_name = _("One-time Alert")
        verbose_name_plural = _("One-time Alerts")


class NotificationRead(models.Model):
    """One user has read one notification (targeted or broadcast). Drives the bell's unread count.

    Race guard: the unique (user, notification) constraint makes marking read idempotent.
    """

    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="notification_reads")
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="reads")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "notification"), name="notification_read_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} read {self.notification_id}"
