"""Channels: one metric read from one source, with protocol-specific addressing."""

from django.db import models
from django.db.models import Q
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel

from .device import TelemetryDevice
from .reference_data import DeviceProfile, MetricDefinition


class TelemetryChannel(TimeStampedModel, UserStampedModel):
    """One metric read from one source (for a bus: one field device at one address).

    What the channel measures is a time-bounded `ChannelTargetBinding`, so moving a sensor never rewrites
    history. `field_device_equipment` optionally records the physical sensor as an inventory asset, which
    is distinct from the target it measures. Application rule (cross-table, not expressible as a CHECK):
    `source.role` is `source`. Owner: telemetry feature.
    """

    source = models.ForeignKey(TelemetryDevice, on_delete=models.PROTECT, related_name="channels")
    metric = models.ForeignKey(MetricDefinition, on_delete=models.PROTECT, related_name="channels")
    label = models.CharField(max_length=120, blank=True, default="")
    is_enabled = models.BooleanField(default=True)
    field_device_equipment = models.ForeignKey(
        "labs.Equipment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="telemetry_field_channels",
        help_text="Optional: the physical sensor or meter as an inventory asset.",
    )

    class Meta:
        app_label = "labs"

    def __str__(self) -> str:
        return f"channel {self.pk} ({self.metric_id})"


class ModbusChannelSettings(TimeStampedModel):
    """Where to read a channel on a Modbus source: unit ID (bus address) and device profile.

    `source` and `metric` are copies of the channel's values so one `(source, unit_id, metric)` is unique
    in the database; the application writes them together with the channel (cross-table equality is
    application-only). Deleted with its channel (no independent meaning). Owner: telemetry feature.
    """

    channel = models.OneToOneField(
        TelemetryChannel, on_delete=models.CASCADE, primary_key=True, related_name="modbus_settings"
    )
    source = models.ForeignKey(TelemetryDevice, on_delete=models.PROTECT, related_name="modbus_channels")
    metric = models.ForeignKey(MetricDefinition, on_delete=models.PROTECT, related_name="modbus_channels")
    unit_id = models.PositiveSmallIntegerField(help_text="Modbus unit ID = RS485 slave address (1-247).")
    profile = models.ForeignKey(DeviceProfile, on_delete=models.PROTECT, related_name="modbus_channels")

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(fields=["source", "unit_id", "metric"], name="telemetry_modbus_channel_uniq"),
            models.CheckConstraint(condition=Q(unit_id__gte=1, unit_id__lte=247), name="telemetry_modbus_unit_range"),
        ]

    def __str__(self) -> str:
        return f"unit {self.unit_id} {self.metric_id}"
