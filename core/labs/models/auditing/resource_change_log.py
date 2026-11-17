from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import QuerySet
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.base.generic_links import resource_content_types


class ResourceChangeLogQuerySet(models.QuerySet):
    def for_resource(self, resource: models.Model) -> QuerySet["ResourceChangeLog"]:
        if resource.pk is None:
            return self.none()
        # New rows use the root content type (e.g. Equipment); rows written
        # before that used the subclass type, so both are matched.
        return self.filter(
            resource_content_type__in=resource_content_types(resource),
            resource_object_id=str(resource.pk),
        )


class ResourceChangeLog(TimeStampedModel, UserStampedModel):
    """Immutable field-level change record for any lab resource."""

    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"

    resource_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name="resource_change_logs",
    )
    resource_object_id = models.CharField(max_length=64)
    resource = GenericForeignKey(
        "resource_content_type",
        "resource_object_id",
        for_concrete_model=False,
    )
    action = models.CharField(max_length=8, choices=Action.choices)
    field_name = models.CharField(max_length=255, blank=True, default="")
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = ResourceChangeLogQuerySet.as_manager()

    class Meta:
        app_label = "labs"
        ordering = ("-created", "-id")
        indexes = [
            models.Index(
                fields=(
                    "resource_content_type",
                    "resource_object_id",
                    "-created",
                ),
                name="resource_change_latest_idx",
            ),
            models.Index(
                fields=("action", "-created"),
                name="resource_change_action_idx",
            ),
        ]

    def __str__(self) -> str:
        target = self.resource or (
            f"{self.resource_content_type.app_label}."
            f"{self.resource_content_type.model}:{self.resource_object_id}"
        )
        field = f".{self.field_name}" if self.field_name else ""
        return f"{target}{field} - {self.get_action_display()}"
