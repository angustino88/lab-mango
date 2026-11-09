"""Shared primitives for durable laboratory analytics records."""
from __future__ import annotations

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel


class AnalyticsSource(models.TextChoices):
    """System responsible for producing an analytics observation."""

    APPLICATION = "application", _("Application")
    COLLECTOR = "collector", _("Collector")
    IMPORT = "import", _("Import")
    MANUAL = "manual", _("Manual")


class AnalyticsGranularity(models.TextChoices):
    """The time scope represented by an aggregated observation."""

    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")
    MONTHLY = "monthly", _("Monthly")
    AD_HOC = "ad_hoc", _("Ad hoc")


class AnalyticsObservation(TimeStampedModel):
    """Abstract immutable measurement for a complete reporting interval.

    Subclasses must name the measured value precisely and are safe to aggregate
    by ``period_start`` and ``granularity``. Observations are retained rather
    than soft-deleted because changing historical analytics corrupts reporting.
    """

    period_start = models.DateTimeField(
        help_text=_("Inclusive start of the interval represented by this observation."),
    )
    period_end = models.DateTimeField(
        help_text=_("Exclusive end of the interval represented by this observation."),
    )
    granularity = models.CharField(
        max_length=16,
        choices=AnalyticsGranularity.choices,
        default=AnalyticsGranularity.DAILY,
    )
    source = models.CharField(
        max_length=16,
        choices=AnalyticsSource.choices,
        default=AnalyticsSource.APPLICATION,
    )
    recorded_at = models.DateTimeField(
        help_text=_("When this measurement was produced or ingested."),
    )

    class Meta:
        abstract = True
        ordering = ("-period_start", "-recorded_at")

    def clean(self) -> None:
        super().clean()
        if self.period_end <= self.period_start:
            raise ValidationError({"period_end": _("Period end must be after period start.")})

    @property
    def interval(self) -> tuple[datetime, datetime]:
        """Return the inclusive/exclusive interval represented by the row."""
        return self.period_start, self.period_end


class AnalyticsEvent(TimeStampedModel):
    """Abstract append-only fact emitted when an operational event occurs."""

    occurred_at = models.DateTimeField(
        help_text=_("Time at which the operational event occurred."),
    )
    source = models.CharField(
        max_length=16,
        choices=AnalyticsSource.choices,
        default=AnalyticsSource.APPLICATION,
    )
    external_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Optional idempotency key from the source system."),
    )

    class Meta:
        abstract = True
        ordering = ("-occurred_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("source", "external_reference"),
                condition=~Q(external_reference=""),
                name="%(app_label)s_%(class)s_source_reference_uniq",
            )
        ]
