from datetime import datetime

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class BookingStatus(models.TextChoices):
    RESERVED = "reserved", _("Reserved")
    IN_PROGRESS = "in_progress", _("In progress")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")
    EXPIRED = "expired", _("Expired")


BOOKING_STATUS_TRANSITIONS = {
    BookingStatus.RESERVED: frozenset({BookingStatus.IN_PROGRESS, BookingStatus.CANCELLED, BookingStatus.EXPIRED}),
    BookingStatus.IN_PROGRESS: frozenset({BookingStatus.COMPLETED, BookingStatus.CANCELLED}),
    BookingStatus.COMPLETED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
    BookingStatus.EXPIRED: frozenset(),
}


class TsTzRange(models.Func):
    """SQL ``tstzrange(starts_at, ends_at, '[)')`` for exclusion constraints."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


def no_overlap_constraint(*, name: str, resource_field: str) -> ExclusionConstraint:
    """Database guarantee that one resource is never double-booked.

    Needs the PostgreSQL ``btree_gist`` extension (BtreeGistExtension migration).
    Only bookings that still reserve the resource (active + pending/approved) count.
    """
    return ExclusionConstraint(
        name=name,
        expressions=[
            (resource_field, RangeOperators.EQUAL),
            (TsTzRange("starts_at", "ends_at", RangeBoundary()), RangeOperators.OVERLAPS),
        ],
        condition=models.Q(
            status__in=[BookingStatus.RESERVED, BookingStatus.IN_PROGRESS],
            approval_status__in=[BookingApprovalStatus.PENDING, BookingApprovalStatus.APPROVED],
        ),
    )


def ensure_booking_status_transition(*, current_status: str, target_status: str) -> None:
    """Reject invalid booking lifecycle transitions, including any terminal-state revival."""
    try:
        allowed_targets = BOOKING_STATUS_TRANSITIONS[BookingStatus(current_status)]
    except ValueError as error:
        raise ValidationError({"status": f"Unknown booking status: {current_status}."}) from error

    if target_status == current_status:
        return

    if target_status not in allowed_targets:
        raise ValidationError({"status": f"Cannot transition booking from {current_status} to {target_status}."})


class BookingApprovalStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")


class Booking(TimeStampedModel, UserStampedModel):
    """Shared workflow and schedule data for reservable lab resources."""

    ACTIVE_STATUSES = frozenset({BookingStatus.RESERVED, BookingStatus.IN_PROGRESS})
    RESERVING_APPROVAL_STATUSES = frozenset({BookingApprovalStatus.PENDING, BookingApprovalStatus.APPROVED})

    booking_code = models.CharField(max_length=64, unique=True, db_index=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=32,
        choices=BookingStatus.choices,
        default=BookingStatus.RESERVED,
        db_index=True,
    )
    approval_status = models.CharField(
        max_length=32,
        choices=BookingApprovalStatus.choices,
        default=BookingApprovalStatus.APPROVED,
        db_index=True,
    )
    project = models.ForeignKey(
        "labs.LabProject",
        related_name="%(class)ss",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="requested_%(class)ss",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Who the booking is for. Defaults to the creator when empty (booking on behalf of someone else).",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="approved_%(class)ss",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")
    cancellation_reason = models.TextField(blank=True, default="")

    @property
    def is_reserving(self) -> bool:
        return self.status in self.ACTIVE_STATUSES and self.approval_status in self.RESERVING_APPROVAL_STATUSES

    @property
    def duration_seconds(self) -> float:
        return (self.ends_at - self.starts_at).total_seconds()

    def overlaps(self, starts_at: datetime, ends_at: datetime) -> bool:
        return self.starts_at < ends_at and self.ends_at > starts_at

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.starts_at is not None and self.ends_at is not None and self.starts_at >= self.ends_at:
            errors["ends_at"] = _("A booking must end after it starts.")
        if self.approval_status == BookingApprovalStatus.REJECTED and self.approved_by_id is None:
            errors["approved_by"] = _("A rejected booking requires an approver.")
        if self.approval_status == BookingApprovalStatus.REJECTED and not self.rejection_reason.strip():
            errors["rejection_reason"] = _("A rejected booking requires a reason.")
        if self.approved_by_id is not None and self.approval_status == BookingApprovalStatus.PENDING:
            errors["approval_status"] = _("A booking with an approver cannot still be pending.")
        if self.status == BookingStatus.CANCELLED and not self.cancellation_reason.strip():
            errors["cancellation_reason"] = _("A cancelled booking requires a reason.")

        if errors:
            raise ValidationError(errors)

    class Meta:
        abstract = True
        ordering = ("-starts_at", "-created")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="%(app_label)s_%(class)s_valid_booking_period",
            ),
        ]
