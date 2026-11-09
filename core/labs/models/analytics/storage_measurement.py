"""Point-in-time storage capacity measurements collected from computing assets."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from .base import AnalyticsSource


class StorageQuotaMeasurement(TimeStampedModel):
    """Storage usage captured for an account on a laboratory computer.

    Measurements are append-only. The account and computer references are
    nullable so a retained measurement remains useful after source-system or
    asset lifecycle changes.
    """

    measured_at = models.DateTimeField(help_text=_("When storage capacity was measured."))
    account_identifier = models.CharField(max_length=255)
    account_display_name = models.CharField(max_length=255, blank=True, default="")
    computer_identifier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Stable asset identifier supplied by the storage collector."),
    )
    used_gibibytes = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0"))],
    )
    quota_gibibytes = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0"))],
    )
    source = models.CharField(
        max_length=16,
        choices=AnalyticsSource.choices,
        default=AnalyticsSource.COLLECTOR,
    )
    source_account_identifier = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ("-measured_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(used_gibibytes__gte=0),
                name="labs_storage_measurement_used_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(quota_gibibytes__gte=0),
                name="labs_storage_measurement_quota_nonnegative",
            ),
            models.UniqueConstraint(
                fields=("computer_identifier", "account_identifier", "measured_at", "source"),
                name="labs_storage_measurement_identity_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("computer_identifier", "measured_at"),
                name="storage_computer_at_idx",
            ),
            models.Index(fields=("account_identifier", "measured_at"), name="storage_account_at_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.used_gibibytes > self.quota_gibibytes:
            raise ValidationError(
                {"used_gibibytes": _("Used capacity cannot exceed the recorded quota.")}
            )

    @property
    def utilization_percent(self) -> Decimal:
        """Return capacity utilization as a percentage, avoiding division by zero."""
        if not self.quota_gibibytes:
            return Decimal("0")
        return (self.used_gibibytes / self.quota_gibibytes * Decimal("100")).quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return f"{self.account_identifier}: {self.used_gibibytes}/{self.quota_gibibytes} GiB"
