
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class SampleCustomer(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(
                fields=("name",),
                opclasses=("gin_trgm_ops",),
                name="sample_customer_name_idx",
            ),
        ]


class SampleCharacteristic(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(
                fields=("name",),
                opclasses=("gin_trgm_ops",),
                name="sample_characteristic_name_idx",
            ),
        ]
