from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class StationSlotStatus(models.TextChoices):
    AVAILABLE = "available", "Available"
    OCCUPIED = "occupied", "Occupied"
    RESERVED = "reserved", "Reserved"
    MAINTENANCE = "maintenance", "Maintenance"
    OUT_OF_SERVICE = "out_of_service", "Out of service"
    RETIRED = "retired", "Retired"


class StationSlot(TimeStampedModel, UserStampedModel):
    """A stable, assignable bench position within a physical station."""

    station = models.ForeignKey(
        "labs.Station",
        related_name="bench_slots",
        on_delete=models.CASCADE,
    )
    position_index = models.PositiveSmallIntegerField()
    slot_code = models.CharField(max_length=32)
    label = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=32, choices=StationSlotStatus, default="available")
    width_mm = models.PositiveIntegerField(null=True, blank=True)
    depth_mm = models.PositiveIntegerField(null=True, blank=True)
    height_mm = models.PositiveIntegerField(null=True, blank=True)
    max_load_kg = models.PositiveIntegerField(null=True, blank=True)
    power_capacity_w = models.PositiveIntegerField(null=True, blank=True)
    network_port_count = models.PositiveSmallIntegerField(null=True, blank=True)
    utilities = models.JSONField(default=dict, blank=True)
    compatible_bench_types = models.ManyToManyField(
        "labs.BenchType",
        related_name="compatible_station_slots",
        blank=True,
    )

    def clean(self) -> None:
        super().clean()
        if self.station_id is None:
            return
        self.slot_code = self.slot_code.strip().upper()
        self.label = self.label.strip()
        if (
            self.station.bench_capacity is not None
            and self.position_index >= self.station.bench_capacity
        ):
            raise ValidationError({
                "position_index": "The position must fit within the station bench capacity."
            })

    def save(self, *args, **kwargs):
        self.slot_code = self.slot_code.strip().upper()
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        app_label = "labs"
        ordering = ("station", "position_index")
        constraints = [
            models.UniqueConstraint(
                fields=("station", "position_index"),
                name="uniq_station_slot_position",
            ),
            models.UniqueConstraint(
                fields=("station", "slot_code"),
                name="uniq_station_slot_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.station} / {self.slot_code}"
