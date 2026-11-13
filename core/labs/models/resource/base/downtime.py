"""Downtime windows of any lab resource, and the computed condition that follows from them.

A resource's *lifecycle* says whether the lab runs it (stored on the resource). Its *condition* says
whether it works right now. Condition is never stored: it is read from the ``ResourceDowntime`` window
that covers the moment (``ResourceCondition``). Design: ``docs/proposals/resource-status-and-downtime.md``.

Rows link to the root resource model (``generic_links``), like ``ResourceServiceRecord``.
"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, CharField, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce, Now
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.booking.base import TsTzRange
from core.labs.models.resource.base.generic_links import (
    resource_content_type,
    resource_content_types,
    resource_root_model,
)
from core.labs.models.resource.base.status import ResourceCondition, ResourceLifecycleStatus


class DowntimeKind(models.TextChoices):
    PLANNED = "planned", _("Planned")
    UNPLANNED = "unplanned", _("Unplanned")


class DowntimeReason(models.TextChoices):
    MAINTENANCE = "maintenance", _("Maintenance")
    FAULT = "fault", _("Fault")
    CALIBRATION = "calibration", _("Calibration")
    SAFETY_HOLD = "safety_hold", _("Safety hold")
    RENOVATION = "renovation", _("Renovation")
    OTHER = "other", _("Other")


DOWNTIME_CONDITIONS = (ResourceCondition.IN_MAINTENANCE, ResourceCondition.OUT_OF_SERVICE)


def _resource_link(model: type[models.Model]) -> Q:
    """Rows of ``model`` matched by app label and model name, so building it needs no database access."""
    linked = {resource_root_model(model), model._meta.concrete_model or model}
    return Q(
        resource_content_type__app_label=model._meta.app_label,
        resource_content_type__model__in=sorted(item._meta.model_name for item in linked),
    )


class ResourceDowntimeQuerySet(models.QuerySet):
    def not_cancelled(self) -> ResourceDowntimeQuerySet:
        return self.filter(cancelled_at__isnull=True)

    def for_resource(self, resource: models.Model) -> ResourceDowntimeQuerySet:
        if resource.pk is None:
            return self.none()
        return self.filter(
            resource_content_type__in=resource_content_types(resource),
            resource_object_id=str(resource.pk),
        )

    def for_resources(self, model: type[models.Model], ids) -> ResourceDowntimeQuerySet:
        return self.filter(_resource_link(model), resource_object_id__in=[str(pk) for pk in ids])

    def overlapping(self, starts_at: datetime, ends_at: datetime | None) -> ResourceDowntimeQuerySet:
        """Windows that share any moment with ``[starts_at, ends_at)``; ``ends_at=None`` is open-ended."""
        queryset = self.not_cancelled().filter(Q(ends_at__isnull=True) | Q(ends_at__gt=starts_at))
        if ends_at is not None:
            queryset = queryset.filter(starts_at__lt=ends_at)
        return queryset

    def current(self, moment: datetime | None = None) -> ResourceDowntimeQuerySet:
        moment = moment or timezone.now()
        return (
            self.not_cancelled().filter(starts_at__lte=moment).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=moment))
        )

    def upcoming(self, moment: datetime | None = None) -> ResourceDowntimeQuerySet:
        return self.not_cancelled().filter(starts_at__gt=moment or timezone.now())

    def worst_first(self) -> ResourceDowntimeQuerySet:
        severity = Case(
            # Q() wraps the field: When() has its own `condition` parameter.
            When(Q(condition=ResourceCondition.OUT_OF_SERVICE), then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
        return self.order_by(severity, "starts_at", "pk")


class ResourceDowntimeManager(models.Manager.from_queryset(ResourceDowntimeQuerySet)):
    def condition_of(self, resource: models.Model, *, at: datetime | None = None) -> str:
        """The condition of one saved resource at ``at`` (default now). One query; never call per row."""
        row = self.for_resource(resource).current(at).worst_first().values_list("condition", flat=True).first()
        return row or ResourceCondition.OPERATIONAL

    def start_now(self, resource: models.Model, *, condition: str, reason: str, notes: str = "", actor=None):
        """Open an unplanned window starting now, or return the current one when it already has ``condition``.

        Persistence primitive for the compatibility write paths (design rule 5). The caller holds the
        resource row lock; it does not check bookings. An existing current window with another condition
        is ended first, so the new condition starts now. The new window has no end, so a window planned
        for later would overlap it: that is refused rather than silently cancelled.
        """
        now = timezone.now()
        current = self.for_resource(resource).current(now).worst_first().select_for_update().first()
        if current is not None and current.condition == condition:
            return current
        if self.for_resource(resource).upcoming(now).exists():
            raise ValidationError(
                {
                    "condition": "Downtime is already planned for this resource. End or cancel it in the downtime API first."
                }
            )
        if current is not None:
            current.end(at=now, actor=actor)
        window = self.model.for_new_resource(
            resource,
            condition=condition,
            kind=DowntimeKind.UNPLANNED,
            reason=reason,
            starts_at=now,
            notes=notes,
        )
        window.full_clean()
        window.save(actor=actor)
        return window

    def end_current(self, resource: models.Model, *, actor=None) -> list[ResourceDowntime]:
        """End every window of ``resource`` that covers now; the caller holds the resource row lock."""
        now = timezone.now()
        windows = list(self.for_resource(resource).current(now).select_for_update().order_by("pk"))
        for window in windows:
            window.end(at=now, actor=actor)
        return windows

    def close_all(self, resource: models.Model, *, actor=None) -> None:
        """End the current windows and cancel future ones (the resource leaves service)."""
        now = timezone.now()
        self.end_current(resource, actor=actor)
        for window in self.for_resource(resource).upcoming(now).select_for_update().order_by("pk"):
            window.cancel(at=now, actor=actor)


class ResourceDowntime(TimeStampedModel, UserStampedModel):
    """One period when a resource cannot be used, planned ahead or recorded when it happens."""

    resource_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="resource_downtimes",
    )
    resource_object_id = models.CharField(max_length=64)
    resource = GenericForeignKey("resource_content_type", "resource_object_id", for_concrete_model=False)

    condition = models.CharField(
        max_length=32,
        choices=[
            (value, label) for value, label in ResourceCondition.choices if value != ResourceCondition.OPERATIONAL
        ],
        help_text="The condition of the resource during the window.",
    )
    kind = models.CharField(max_length=16, choices=DowntimeKind.choices, default=DowntimeKind.UNPLANNED)
    reason = models.CharField(max_length=32, choices=DowntimeReason.choices, default=DowntimeReason.OTHER)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Empty while the end is not known.")
    notes = models.TextField(blank=True, default="")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="ended_resource_downtimes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    objects = ResourceDowntimeManager()

    @classmethod
    def for_new_resource(cls, resource: models.Model, **fields) -> ResourceDowntime:
        """Build a window linked to the root content type of ``resource``."""
        return cls(
            resource_content_type=resource_content_type(resource),
            resource_object_id=str(resource.pk),
            **fields,
        )

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None

    def end(self, *, at: datetime, actor=None) -> None:
        self.ends_at = at
        self.ended_by = actor if getattr(actor, "is_authenticated", False) else None
        self.save(actor=actor, update_fields=("ends_at", "ended_by", "modified"))

    def cancel(self, *, at: datetime, actor=None) -> None:
        self.cancelled_at = at
        self.save(actor=actor, update_fields=("cancelled_at", "modified"))

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.resource_content_type_id:
            model = self.resource_content_type.model_class()
            if model is None or resource_root_model(model) is not model:
                errors["resource_content_type"] = _("Use the root resource model, e.g. Equipment.")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("The end must be after the start.")
        self.notes = (self.notes or "").strip()
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.get_condition_display()} {self.starts_at:%Y-%m-%d %H:%M} ({self.resource_object_id})"

    class Meta:
        app_label = "labs"
        ordering = ("-starts_at", "-id")
        indexes = [
            models.Index(
                fields=("resource_content_type", "resource_object_id", "starts_at"),
                name="downtime_resource_start_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="downtime_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(condition__in=[str(value) for value in DOWNTIME_CONDITIONS]),
                name="downtime_condition_valid",
            ),
            models.CheckConstraint(condition=Q(kind__in=DowntimeKind.values), name="downtime_kind_valid"),
            models.CheckConstraint(condition=Q(reason__in=DowntimeReason.values), name="downtime_reason_valid"),
            ExclusionConstraint(
                name="downtime_no_overlap",
                expressions=[
                    ("resource_content_type", RangeOperators.EQUAL),
                    ("resource_object_id", RangeOperators.EQUAL),
                    (TsTzRange("starts_at", "ends_at", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
                condition=Q(cancelled_at__isnull=True),
            ),
        ]


def outer_windows(model: type[models.Model], *, outer_ref: str = "pk") -> ResourceDowntimeQuerySet:
    """Correlated subquery base: every window of the outer ``model`` row (``outer_ref`` holds its pk)."""
    return ResourceDowntime.objects.filter(
        _resource_link(model), resource_object_id=Cast(OuterRef(outer_ref), CharField())
    )


def current_downtime(model: type[models.Model], *, outer_ref: str = "pk") -> ResourceDowntimeQuerySet:
    """Correlated subquery base: the windows of the outer ``model`` row that cover now, worst first."""
    return (
        outer_windows(model, outer_ref=outer_ref)
        .filter(cancelled_at__isnull=True, starts_at__lte=Now())
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=Now()))
        .worst_first()
    )


def condition_expression(model: type[models.Model], *, outer_ref: str = "pk") -> Coalesce:
    """Annotation: the computed ``ResourceCondition`` of each outer row (one correlated subquery)."""
    return Coalesce(
        Subquery(current_downtime(model, outer_ref=outer_ref).values("condition")[:1]),
        Value(ResourceCondition.OPERATIONAL.value),
        output_field=CharField(),
    )


def downtime_reason_expression(model: type[models.Model], *, outer_ref: str = "pk") -> Subquery:
    """Annotation: the reason of the window behind ``condition_expression`` (null when operational)."""
    return Subquery(current_downtime(model, outer_ref=outer_ref).values("reason")[:1], output_field=CharField())


__all__ = [
    "DOWNTIME_CONDITIONS",
    "DowntimeKind",
    "DowntimeReason",
    "ResourceCondition",
    "ResourceDowntime",
    "ResourceLifecycleStatus",
    "condition_expression",
    "current_downtime",
    "downtime_reason_expression",
    "outer_windows",
]
