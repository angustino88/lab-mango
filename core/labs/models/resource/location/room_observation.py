from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from model_utils.models import TimeStampedModel


class RoomObservation(TimeStampedModel):
    """Timestamped room telemetry with explicit units and source attribution."""

    room = models.ForeignKey("labs.Room", on_delete=models.PROTECT, related_name="observations")
    observed_at = models.DateTimeField()
    source = models.CharField(max_length=100)
    temperature_c = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("-273.15"))],
        null=True,
        blank=True,
    )
    humidity_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        null=True,
        blank=True,
    )
    power_usage_w = models.PositiveIntegerField(null=True, blank=True)

    def clean(self) -> None:
        super().clean()
        if all(value is None for value in (self.temperature_c, self.humidity_percent, self.power_usage_w)):
            raise ValidationError("An observation must contain at least one measurement.")

    class Meta:
        app_label = "labs"
        ordering = ("-observed_at", "-pk")
        indexes = [
            models.Index(
                fields=("room", "-observed_at"),
                name="room_observation_time_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(temperature_c__isnull=False)
                    | models.Q(humidity_percent__isnull=False)
                    | models.Q(power_usage_w__isnull=False)
                ),
                name="room_observation_has_value",
            ),
            models.CheckConstraint(
                condition=models.Q(temperature_c__isnull=True) | models.Q(temperature_c__gte=Decimal("-273.15")),
                name="room_temperature_physical_min",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(humidity_percent__isnull=True)
                    | models.Q(humidity_percent__gte=0, humidity_percent__lte=100)
                ),
                name="room_humidity_valid_range",
            ),
        ]
