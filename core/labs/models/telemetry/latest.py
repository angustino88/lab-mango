"""The most recent reading of each telemetry channel: what dashboards show "now"."""

from django.db import models
from django.db.models import Q

from .channel import TelemetryChannel
from .device import TelemetryDevice
from .reference_data import MetricDefinition
from .target import TelemetryTarget


class TelemetryReadingStatus(models.TextChoices):
    OK = "ok", "OK"
    NO_RESPONSE = "no_response", "No response"
    ERROR = "error", "Error"


class TelemetryLatest(models.Model):
    """One row per channel, replaced only by a newer observation (proposal §6.8).

    `value` is null unless `status` is ok (a channel that did not answer is never stored as 0). `target` is the
    channel's bound target at `observed_at`; dashboards roll targets up to their station and room through
    placement. Writes come only from gateway ingest. Owner: telemetry feature.
    """

    channel = models.OneToOneField(TelemetryChannel, on_delete=models.CASCADE, related_name="latest")
    target = models.ForeignKey(TelemetryTarget, on_delete=models.PROTECT, related_name="latest_readings")
    metric = models.ForeignKey(MetricDefinition, on_delete=models.PROTECT, related_name="latest_readings")
    gateway = models.ForeignKey(TelemetryDevice, on_delete=models.PROTECT, related_name="latest_ingested")
    sample_id = models.UUIDField(help_text="The source poll cycle that produced this reading (idempotency).")
    observed_at = models.DateTimeField()
    received_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=TelemetryReadingStatus.choices)
    value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)

    class Meta:
        app_label = "labs"
        indexes = [models.Index(fields=["metric", "observed_at"], name="telemetry_latest_metric_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(status="ok", value__isnull=False) | (~Q(status="ok") & Q(value__isnull=True)),
                name="telemetry_latest_value_matches_status",
            ),
            models.CheckConstraint(
                condition=~Q(metric_id="humidity_percent") | Q(value__isnull=True) | Q(value__gte=0, value__lte=100),
                name="telemetry_latest_humidity_range",
            ),
            models.CheckConstraint(
                condition=~Q(metric_id="temperature_c") | Q(value__isnull=True) | Q(value__gte=-273.15),
                name="telemetry_latest_temperature_range",
            ),
            models.CheckConstraint(
                condition=~Q(metric_id="power_w") | Q(value__isnull=True) | Q(value__gte=0),
                name="telemetry_latest_power_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel_id}={self.value}@{self.observed_at}"
