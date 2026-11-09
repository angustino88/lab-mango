from typing import TYPE_CHECKING

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.base.resource import ResourceModel, ResourceStatusRecordModel
from core.labs.models.resource.location.physical_location import PhysicalLocationNode

if TYPE_CHECKING:
    from core.labs.models.resource.location.room import Room


class StationType(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)


class Station(ResourceModel, PhysicalLocationNode):
    """A physical station optionally placed in one of its room's slots."""

    IMAGE_UPLOAD_FOLDER = "station"

    type = models.ForeignKey(
        "labs.StationType",
        related_name="stations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    room = models.ForeignKey(
        "labs.Room",
        related_name="stations",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    slot = models.ForeignKey(
        "labs.RoomSlot",
        related_name="stations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    position = ArrayField(
        models.FloatField(
            validators=[
                MinValueValidator(-1000000.0),
                MaxValueValidator(1000000.0),
            ],
        ),
        size=3,
        null=True,
        blank=True,
    )
    height_mm = models.PositiveIntegerField(null=True, blank=True)
    width_mm = models.PositiveIntegerField(null=True, blank=True)
    depth_mm = models.PositiveIntegerField(null=True, blank=True)
    orientation_degrees = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(359)],
        default=0,
    )
    max_load_kg = models.PositiveIntegerField(null=True, blank=True)
    bench_capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    max_concurrent_users = models.PositiveSmallIntegerField(null=True, blank=True)
    usable_surface_mm2 = models.PositiveBigIntegerField(null=True, blank=True)
    power_capacity_w = models.PositiveIntegerField(null=True, blank=True)
    power_reserved_w = models.PositiveIntegerField(default=0)
    cooling_capacity_w = models.PositiveIntegerField(null=True, blank=True)
    network_port_capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    utilities = models.JSONField(default=dict, blank=True)
    safety_classification = models.CharField(max_length=64, blank=True, default="")

    def clean(self) -> None:
        """Validate placement before writes and during explicit model validation."""
        super().clean()
        self.safety_classification = self.safety_classification.strip()
        if (
            self.power_capacity_w is not None
            and self.power_reserved_w > self.power_capacity_w
        ):
            raise ValidationError({
                "power_reserved_w": "Reserved power must not exceed station power capacity."
            })
        if self.slot_id is None:
            return
        if self.room_id is None:
            raise ValidationError({"slot": "A station must have a room before assigning a slot."})
        if self.slot.room_id != self.room_id:
            raise ValidationError({"slot": "The assigned slot must belong to the station's room."})

    @property
    def available_power_w(self) -> int | None:
        if self.power_capacity_w is None:
            return None
        return self.power_capacity_w - self.power_reserved_w

    def get_location_parent(self) -> "Room | None":
        """Return the containing room, or None for an unassigned station."""
        return self.room

    def get_location_segment(self) -> str | None:
        """Return the station's physical label, falling back to its SKU or name."""
        return self.label or self.sku or self.name

    class Meta:
        app_label = "labs"
        constraints = [*ResourceModel.Meta.constraints,
            models.UniqueConstraint(
                fields=("slot",),
                condition=models.Q(slot__isnull=False),
                name="station_slot_uniq",
            ),
        ]


class StationStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    RESERVED = "reserved", _("Reserved")
    ISSUE = "issue", _("Issue")
    RESTRICTED = "restricted", _("Restricted")
    CLOSED = "closed", _("Closed")
    MAINTENANCE = "maintenance", _("Maintenance")
    RETIRED = "retired", _("Retired")


class StationStatusRecord(ResourceStatusRecordModel):
    station = models.ForeignKey(
        "labs.Station",
        related_name="status_records",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=255,
        choices=StationStatus.choices,
    )

    class Meta:
        app_label = "labs"
        ordering = ("-created", "-id")
        indexes = [
            models.Index(fields=("station", "-created", "-id"), name="station_status_latest_idx"),
        ]
