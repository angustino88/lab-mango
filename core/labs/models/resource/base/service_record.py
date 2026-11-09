from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q, QuerySet
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.base.generic_links import (
    resource_content_type,
    resource_content_types,
    resource_root_model,
)


class ResourceServiceRecordQuerySet(models.QuerySet):
    def for_resource(self, resource: models.Model) -> QuerySet["ResourceServiceRecord"]:
        if resource.pk is None:
            return self.none()
        return self.filter(
            resource_content_type__in=resource_content_types(resource),
            resource_object_id=str(resource.pk),
        )

    def due_before(self, moment) -> QuerySet["ResourceServiceRecord"]:
        return self.filter(next_due_at__isnull=False, next_due_at__lt=moment)


class ResourceServiceRecord(TimeStampedModel, UserStampedModel):
    """Calibration, inspection, maintenance or safety test of ANY lab resource.

    One generic history replaces per-model fields such as
    ``Bench.last_inspected_at`` and instrument-only calibration dates.
    Always link to the root model (see ``generic_links``).
    """

    class Kind(models.TextChoices):
        CALIBRATION = "calibration", _("Calibration")
        INSPECTION = "inspection", _("Inspection")
        MAINTENANCE = "maintenance", _("Maintenance")
        SAFETY_TEST = "safety_test", _("Safety test")

    class Result(models.TextChoices):
        PASS = "pass", _("Pass")
        FAIL = "fail", _("Fail")
        ADJUSTED = "adjusted", _("Adjusted")

    resource_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="resource_service_records",
    )
    resource_object_id = models.CharField(max_length=64)
    resource = GenericForeignKey("resource_content_type", "resource_object_id", for_concrete_model=False)

    kind = models.CharField(max_length=16, choices=Kind.choices)
    performed_at = models.DateTimeField()
    next_due_at = models.DateTimeField(null=True, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="performed_service_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    vendor = models.CharField(max_length=255, blank=True, default="")
    result = models.CharField(max_length=12, choices=Result.choices, default=Result.PASS)
    certificate_no = models.CharField(max_length=100, blank=True, default="")
    certificate = models.FileField(upload_to="service_certificates/", null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    objects = ResourceServiceRecordQuerySet.as_manager()

    @classmethod
    def for_new_resource(cls, resource: models.Model, **fields) -> "ResourceServiceRecord":
        """Build a record linked to the root content type of ``resource``."""
        return cls(
            resource_content_type=resource_content_type(resource),
            resource_object_id=str(resource.pk),
            **fields,
        )

    def clean(self) -> None:
        super().clean()
        errors = {}
        if self.resource_content_type_id:
            model = self.resource_content_type.model_class()
            if model is None or resource_root_model(model) is not model:
                errors["resource_content_type"] = _("Use the root resource model, e.g. Equipment.")
        if self.performed_at and self.next_due_at and self.next_due_at <= self.performed_at:
            errors["next_due_at"] = _("The next due date must be after the service date.")
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.performed_at:%Y-%m-%d} ({self.resource_object_id})"

    class Meta:
        app_label = "labs"
        ordering = ("-performed_at", "-id")
        indexes = [
            models.Index(
                fields=("resource_content_type", "resource_object_id", "kind", "-performed_at"),
                name="service_record_latest_idx",
            ),
            models.Index(fields=("kind", "next_due_at"), name="service_record_due_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(next_due_at__isnull=True) | Q(next_due_at__gt=F("performed_at")),
                name="service_record_due_after_service",
            ),
        ]
