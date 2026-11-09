from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class BenchType(TimeStampedModel, UserStampedModel):
    """Reference data describing the purpose of a test workspace."""

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, default="")
    active = models.BooleanField(default=True, db_index=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(condition=~models.Q(name=""), name="bench_type_name_not_empty"),
        ]
