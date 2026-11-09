from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class LabProject(TimeStampedModel, UserStampedModel):
    """A project that bookings and usage are charged to."""

    project_name = models.CharField(max_length=255, db_index=True, blank=True, default="")
    code = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="Short unique project code, e.g. a cost-center number.",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="owned_lab_projects",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True, db_index=True)

    @property
    def name(self) -> str:
        return self.project_name or ""

    def __str__(self) -> str:
        return self.project_name or self.code or ""

    class Meta:
        app_label = "labs"
        ordering = ("project_name",)
        constraints = [
            models.UniqueConstraint(
                Lower("project_name"),
                condition=~Q(project_name=""),
                name="lab_project_name_uniq",
            ),
            models.CheckConstraint(
                condition=Q(starts_on__isnull=True) | Q(ends_on__isnull=True) | Q(ends_on__gte=F("starts_on")),
                name="lab_project_valid_dates",
            ),
        ]
        indexes = [
            GinIndex(fields=("project_name",), opclasses=["gin_trgm_ops"], name="lab_project_name_trgm_idx"),
        ]
