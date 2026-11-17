"""Ordered device observations; independent of equipment lifecycle and activity."""

from django.db import models
from django.db.models import Q


class DeviceConnectionState(models.TextChoices):
    CONNECTED = "connected", "Connected"
    DISCONNECTED = "disconnected", "Disconnected"


class DeviceMatchStatus(models.TextChoices):
    MATCHED = "matched", "Matched"
    UNMATCHED = "unmatched", "Unmatched"
    AMBIGUOUS = "ambiguous", "Ambiguous"
    INTERFACE_MISMATCH = "interface_mismatch", "Interface mismatch"


class DeviceObservationCursor(models.Model):
    """Last applied batch of one collector on one computer.

    Sequences are contiguous within a generation, so the cursor's timestamps confirm the
    whole collector state, including devices the latest incremental batch did not mention.
    """

    computer = models.ForeignKey(
        "labs.Equipment",
        related_name="deviceobservationcursor_set",
        related_query_name="deviceobservationcursor",
        on_delete=models.PROTECT,
    )
    collector_key = models.CharField(max_length=32)
    generation_key = models.UUIDField()
    sequence = models.PositiveBigIntegerField()
    is_current = models.BooleanField(default=False)
    last_collected_at = models.DateTimeField()
    last_received_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("computer", "collector_key"), name="device_cursor_computer_collector"),
            models.CheckConstraint(condition=Q(sequence__gte=1), name="device_cursor_sequence_positive"),
        ]


class DeviceObservationBatch(models.Model):
    """Idempotency receipt for one reported batch; purged after the retention window."""

    computer = models.ForeignKey(
        "labs.Equipment",
        related_name="deviceobservationbatch_set",
        related_query_name="deviceobservationbatch",
        on_delete=models.PROTECT,
    )
    generation_key = models.UUIDField()
    batch_key = models.UUIDField()
    collector_key = models.CharField(max_length=32)
    sequence = models.PositiveBigIntegerField()
    content_hash = models.CharField(max_length=64)
    is_applied = models.BooleanField(default=False)
    received_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("computer", "generation_key", "batch_key"), name="device_batch_replay_key"
            ),
            models.UniqueConstraint(
                fields=("computer", "generation_key", "collector_key", "sequence"), name="device_batch_sequence"
            ),
            models.CheckConstraint(condition=Q(sequence__gte=1), name="device_batch_sequence_positive"),
        ]
        indexes = [models.Index(fields=("received_at",), name="device_batch_received_idx")]


class DeviceConnection(models.Model):
    """Current projection of one observed device instance on one computer collector.

    ``equipment`` and ``interface`` are derived inventory matches. They are cleared, not
    protected, when the referenced inventory row is removed.
    """

    computer = models.ForeignKey("labs.Equipment", related_name="device_connections", on_delete=models.PROTECT)
    equipment = models.ForeignKey(
        "labs.Equipment", null=True, blank=True, related_name="observed_connections", on_delete=models.SET_NULL
    )
    interface = models.ForeignKey(
        "labs.EquipmentInterface",
        null=True,
        blank=True,
        related_name="deviceconnection_set",
        related_query_name="deviceconnection",
        on_delete=models.SET_NULL,
    )
    collector_key = models.CharField(max_length=32)
    observation_key = models.CharField(max_length=255)
    generation_key = models.UUIDField()
    name = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)
    interface_name = models.CharField(max_length=255)
    state = models.CharField(max_length=16, choices=DeviceConnectionState.choices)
    match_status = models.CharField(max_length=24, choices=DeviceMatchStatus.choices)
    observed_at = models.DateTimeField()
    received_at = models.DateTimeField()
    first_seen_at = models.DateTimeField()
    sequence = models.PositiveBigIntegerField()

    class Meta:
        ordering = ("collector_key", "observation_key", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("computer", "collector_key", "observation_key"), name="device_connection_observation"
            ),
            models.CheckConstraint(condition=Q(sequence__gte=1), name="device_connection_sequence_positive"),
            models.CheckConstraint(
                condition=Q(state__in=DeviceConnectionState.values), name="device_connection_valid_state"
            ),
            models.CheckConstraint(
                condition=Q(match_status__in=DeviceMatchStatus.values), name="device_connection_valid_match"
            ),
        ]
        indexes = [
            models.Index(
                fields=("received_at",),
                condition=Q(state="disconnected"),
                name="device_connection_detached_idx",
            ),
        ]
