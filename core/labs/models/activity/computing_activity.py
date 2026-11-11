from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel


class ComputingActivityStatus(models.TextChoices):
    OFFLINE = "offline", _("Offline")
    FREE = "free", _("Free")
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")
    MAINTAINING = "maintaining", _("Maintaining")


class ComputingActivity(TimeStampedModel):
    """Current activity and remote-access state of a computing resource."""

    computing = models.OneToOneField(
        "labs.Equipment",
        related_name="activity",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=16,
        choices=ComputingActivityStatus.choices,
        default=ComputingActivityStatus.OFFLINE,
        db_index=True,
    )
    remote_user = models.CharField(max_length=255, blank=True, default="")
    remote_user_display_name = models.CharField(max_length=255, blank=True, default="")
    remote_computer = models.CharField(max_length=255, blank=True, default="")
    remote_ip = models.GenericIPAddressField(null=True, blank=True)
    booking_code = models.CharField(max_length=255, blank=True, default="")
    last_agent_report_at = models.DateTimeField(null=True, blank=True)
    offline_at = models.DateTimeField(null=True, blank=True)
    inactive_at = models.DateTimeField(null=True, blank=True)
    inactive_reminder_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=(~Q(status=ComputingActivityStatus.OFFLINE) | Q(offline_at__isnull=False)),
                name="labs_comp_activity_offline_at_required",
            ),
            models.CheckConstraint(
                condition=(~Q(status=ComputingActivityStatus.INACTIVE) | Q(inactive_at__isnull=False)),
                name="labs_comp_activity_inactive_at_required",
            ),
        ]
