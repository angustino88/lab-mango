from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import QuerySet
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.base.generic_links import resource_content_types


class ResourceAuditQuerySet(models.QuerySet):
    def for_resource(self, resource: models.Model) -> QuerySet["ResourceAudit"]:
        if resource.pk is None:
            return self.none()
        # New rows use the root content type (e.g. Equipment); rows written
        # before that used the subclass type, so both are matched.
        return self.filter(
            resource_content_type__in=resource_content_types(resource),
            resource_object_id=str(resource.pk),
        )


class ResourceAudit(TimeStampedModel, UserStampedModel):
    """Historical audit record for a lab resource."""

    class Result(models.TextChoices):
        PASS = "PASS", "Pass"
        FAIL = "FAIL", "Fail"
        NOT_ASSESSED = "NOT_ASSESSED", "Not assessed"

    resource_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="resource_audits",
    )
    resource_object_id = models.CharField(max_length=64)
    resource = GenericForeignKey(
        "resource_content_type",
        "resource_object_id",
        for_concrete_model=False,
    )
    audited_at = models.DateTimeField()
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="resource_audits",
        on_delete=models.PROTECT,
    )
    result = models.CharField(
        max_length=12,
        choices=Result.choices,
    )
    remarks = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    objects = ResourceAuditQuerySet.as_manager()

    class Meta:
        app_label = "labs"
        ordering = ("-audited_at", "-id")
        indexes = [
            models.Index(
                fields=(
                    "resource_content_type",
                    "resource_object_id",
                    "-audited_at",
                ),
                name="resource_audit_latest_idx",
            ),
            models.Index(
                fields=("result", "-audited_at"),
                name="resource_audit_result_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.resource is None:
            raise ValidationError({"resource_object_id": "Resource must exist."})

    def __str__(self) -> str:
        return (
            f"{self.resource} - "
            f"{self.get_result_display()} - "
            f"{self.audited_at:%Y-%m-%d}"
        )
