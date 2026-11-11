
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class NetworkingProtocol(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=25, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(
                fields=("name",),
                opclasses=("gin_trgm_ops",),
                name="networking_protocol_idx",
            ),
        ]
