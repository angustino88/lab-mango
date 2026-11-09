from django.db import models
from django.db.models import Q
from django.utils import timezone

ENTITY_TYPE_CHOICES = (
    # Retained temporarily for compatibility with the already-applied R0 schema.
    ("equipment", "Equipment"),
    ("agent_keys", "Agent keys"),
    ("users", "Users"),
    ("agents", "Agents"),
)


class RoutingChange(models.Model):
    """Immutable versioned routing event, including its historical payload."""

    class Operation(models.TextChoices):
        UPSERT = "upsert", "Upsert"
        DELETE = "delete", "Delete"

    entity_type = models.CharField(max_length=32, choices=ENTITY_TYPE_CHOICES)
    version = models.PositiveBigIntegerField()
    key = models.CharField(max_length=128)
    op = models.CharField(max_length=8, choices=Operation.choices)
    state = models.CharField(max_length=32, null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    data_hash = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "labs_routingchange"
        ordering = ("entity_type", "version")
        constraints = [
            models.CheckConstraint(
                condition=Q(entity_type__in=("equipment", "agent_keys", "users", "agents")),
                name="routing_change_stream_valid",
            ),
            models.CheckConstraint(
                condition=Q(op__in=("upsert", "delete")),
                name="routing_change_operation_valid",
            ),
            models.UniqueConstraint(
                fields=("entity_type", "version"),
                name="routing_change_stream_ver_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        op="upsert",
                        state__isnull=False,
                        data__isnull=False,
                        data_hash__isnull=False,
                    )
                    | Q(
                        op="delete",
                        state__isnull=True,
                        data__isnull=True,
                        data_hash__isnull=True,
                    )
                ),
                name="routing_change_payload_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("entity_type", "key", "version"),
                name="routing_change_key_ver_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.version}:{self.key}:{self.op}"
