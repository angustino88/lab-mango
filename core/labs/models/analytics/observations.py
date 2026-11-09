"""Aggregated, time-bounded key performance indicators for laboratory operations."""
from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import AnalyticsObservation


class ActiveUserObservation(AnalyticsObservation):
    """Count of active users measured across the observation interval."""

    active_user_count = models.PositiveIntegerField(validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("period_start", "period_end", "granularity", "source"),
                name="labs_active_user_observation_period_source_uniq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d}: {self.active_user_count} active users"


class ActiveLaboratoryObservation(AnalyticsObservation):
    """Count of active laboratories measured across the observation interval."""

    active_laboratory_count = models.PositiveIntegerField(validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("period_start", "period_end", "granularity", "source"),
                name="labs_active_lab_observation_period_source_uniq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d}: {self.active_laboratory_count} active laboratories"


class BookingVolumeObservation(AnalyticsObservation):
    """Number of bookings created during the observation interval."""

    booking_count = models.PositiveIntegerField(validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("period_start", "period_end", "granularity", "source"),
                name="labs_booking_volume_observation_period_source_uniq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d}: {self.booking_count} bookings"


class VisitorVolumeObservation(AnalyticsObservation):
    """Number of distinct laboratory visitors during the interval."""

    distinct_visitor_count = models.PositiveIntegerField(validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("period_start", "period_end", "granularity", "source"),
                name="labs_visitor_volume_observation_period_source_uniq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d}: {self.distinct_visitor_count} visitors"


class ResourceUtilizationObservation(AnalyticsObservation):
    """Booked and available duration measured for one laboratory resource."""

    resource_identifier = models.CharField(
        max_length=255,
        help_text=_("Stable identifier supplied by the resource scheduling system."),
    )
    resource_kind = models.CharField(
        max_length=32,
        help_text=_("Resource category, such as equipment or bench."),
    )
    booked_seconds = models.PositiveBigIntegerField(validators=[MinValueValidator(0)])
    available_seconds = models.PositiveBigIntegerField(validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(booked_seconds__lte=models.F("available_seconds")),
                name="labs_resource_utilization_booked_within_available",
            ),
            models.UniqueConstraint(
                fields=(
                    "resource_identifier",
                    "resource_kind",
                    "period_start",
                    "period_end",
                    "granularity",
                    "source",
                ),
                name="labs_resource_utilization_period_source_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("resource_identifier", "period_start"),
                name="utilization_identifier_idx",
            ),
            models.Index(
                fields=("resource_kind", "period_start"),
                name="utilization_kind_idx",
            ),
        ]

    @property
    def utilization_percent(self) -> float:
        """Return booked time as a percentage of the available duration."""
        if not self.available_seconds:
            return 0.0
        return self.booked_seconds / self.available_seconds * 100

    def __str__(self) -> str:
        return f"{self.resource_kind} {self.resource_identifier}: {self.utilization_percent:.1f}% utilized"


class BookingOutcomeObservation(AnalyticsObservation):
    """Booking workflow outcomes measured during a reporting interval."""

    resource_kind = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=_("Optional resource category, such as equipment or bench."),
    )
    completed_count = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    cancelled_count = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    expired_count = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    rejected_count = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("resource_kind", "period_start", "period_end", "granularity", "source"),
                name="labs_booking_outcome_period_source_uniq",
            )
        ]

    @property
    def total_count(self) -> int:
        """Return the total number of terminal booking outcomes."""
        return self.completed_count + self.cancelled_count + self.expired_count + self.rejected_count

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d}: {self.total_count} booking outcomes"


class LaboratoryAvailabilityObservation(AnalyticsObservation):
    """Availability and interruption duration measured for one laboratory."""

    laboratory_identifier = models.CharField(
        max_length=255,
        help_text=_("Stable identifier supplied by the laboratory operations system."),
    )
    available_seconds = models.PositiveBigIntegerField(validators=[MinValueValidator(0)])
    unavailable_seconds = models.PositiveBigIntegerField(validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "laboratory_identifier",
                    "period_start",
                    "period_end",
                    "granularity",
                    "source",
                ),
                name="labs_lab_availability_period_source_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("laboratory_identifier", "period_start"),
                name="lab_availability_lab_idx",
            )
        ]

    @property
    def availability_percent(self) -> float:
        """Return available time as a percentage of total tracked time."""
        tracked_seconds = self.available_seconds + self.unavailable_seconds
        if not tracked_seconds:
            return 0.0
        return self.available_seconds / tracked_seconds * 100

    def __str__(self) -> str:
        return f"{self.laboratory_identifier}: {self.availability_percent:.1f}% available"


class ProjectUsageObservation(AnalyticsObservation):
    """Resource consumption attributed to one laboratory project."""

    project = models.ForeignKey(
        "labs.LabProject",
        related_name="usage_observations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    project_identifier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Stable external project identifier retained after project removal."),
    )
    booking_count = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    booked_seconds = models.PositiveBigIntegerField(default=0, validators=[MinValueValidator(0)])

    class Meta(AnalyticsObservation.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "project",
                    "project_identifier",
                    "period_start",
                    "period_end",
                    "granularity",
                    "source",
                ),
                name="labs_project_usage_period_source_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("project", "period_start"), name="project_usage_project_idx"),
            models.Index(
                fields=("project_identifier", "period_start"),
                name="project_usage_identifier_idx",
            ),
        ]

    def __str__(self) -> str:
        project_reference = self.project_identifier or str(self.project_id or "unassigned")
        return f"{project_reference}: {self.booking_count} bookings"
