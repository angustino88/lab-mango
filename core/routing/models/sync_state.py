import uuid

from django.db import models
from django.db.models import Q

from .routing_change import ENTITY_TYPE_CHOICES


class SyncState(models.Model):
    """Current version and epoch for one routing change stream."""

    entity_type = models.CharField(max_length=32, choices=ENTITY_TYPE_CHOICES, primary_key=True)
    version = models.PositiveBigIntegerField(default=0)
    epoch = models.UUIDField(default=uuid.uuid4)

    class Meta:
        db_table = "labs_syncstate"
        ordering = ("entity_type",)
        verbose_name = "routing sync state"
        verbose_name_plural = "routing sync states"
        constraints = [
            models.CheckConstraint(
                condition=Q(entity_type__in=("equipment", "agent_keys", "users", "agents")),
                name="routing_sync_stream_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}@{self.version}"
