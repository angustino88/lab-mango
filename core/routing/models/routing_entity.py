from django.db import models
from django.db.models import Q

from .routing_change import ENTITY_TYPE_CHOICES


class RoutingEntity(models.Model):
    """Current routing projection row; deletes remain as payload-free tombstones."""

    entity_type = models.CharField(max_length=32, choices=ENTITY_TYPE_CHOICES)
    key = models.CharField(max_length=128)
    version = models.PositiveBigIntegerField()
    state = models.CharField(max_length=32, null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    data_hash = models.CharField(max_length=64, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "labs_routingentity"
        constraints = [
            models.CheckConstraint(
                condition=Q(entity_type__in=("equipment", "agent_keys", "users", "agents")),
                name="routing_entity_stream_valid",
            ),
            models.UniqueConstraint(
                fields=("entity_type", "key"),
                name="routing_entity_stream_key_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        deleted_at__isnull=True,
                        state__isnull=False,
                        data__isnull=False,
                        data_hash__isnull=False,
                    )
                    | Q(
                        deleted_at__isnull=False,
                        state__isnull=True,
                        data__isnull=True,
                        data_hash__isnull=True,
                    )
                ),
                name="routing_entity_payload_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.key}@{self.version}"
