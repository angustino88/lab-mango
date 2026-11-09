from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class RoomSlot(TimeStampedModel, UserStampedModel):
    SLOT_TYPES = (
        ("station", "Station"),
        ("storage", "Storage"),
        ("aisle", "Aisle"),
        ("safety", "Safety"),
        ("utility", "Utility"),
        ("reserved", "Reserved"),
    )
    STATUSES = (
        ("available", "Available"),
        ("occupied", "Occupied"),
        ("blocked", "Blocked"),
        ("maintenance", "Maintenance"),
        ("retired", "Retired"),
    )

    room = models.ForeignKey(
        "labs.Room",
        related_name="slots",
        on_delete=models.CASCADE,
    )
    row_index = models.PositiveIntegerField()
    col_index = models.PositiveIntegerField()
    slot_code = models.CharField(max_length=16)
    slot_type = models.CharField(max_length=16, choices=SLOT_TYPES, default="station")
    status = models.CharField(max_length=16, choices=STATUSES, default="available")
    x_mm = models.IntegerField(null=True, blank=True)
    y_mm = models.IntegerField(null=True, blank=True)
    width_mm = models.PositiveIntegerField(null=True, blank=True)
    depth_mm = models.PositiveIntegerField(null=True, blank=True)
    orientation_degrees = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(359)],
        default=0,
    )
    max_load_kg = models.PositiveIntegerField(null=True, blank=True)
    power_capacity_w = models.PositiveIntegerField(null=True, blank=True)
    utilities = models.JSONField(default=dict, blank=True)
    is_accessible = models.BooleanField(default=False)
    clearance_width_mm = models.PositiveIntegerField(null=True, blank=True)

    def clean(self) -> None:
        super().clean()
        self.slot_code = self.slot_code.strip().upper()

        if self.room_id is None:
            return

        if (
            self.room.layout_rows is not None
            and self.row_index >= self.room.layout_rows
        ):
            raise ValidationError({
                "row_index": "The row must fit within the room layout."
            })

        if (
            self.room.layout_columns is not None
            and self.col_index >= self.room.layout_columns
        ):
            raise ValidationError({
                "col_index": "The column must fit within the room layout."
            })

        if (self.x_mm is None) != (self.y_mm is None):
            raise ValidationError({"x_mm": "Both x_mm and y_mm must be provided together."})

        if (self.width_mm is None) != (self.depth_mm is None):
            raise ValidationError({"width_mm": "Both width_mm and depth_mm must be provided together."})

    def save(self, *args, **kwargs):
        self.slot_code = self.slot_code.strip().upper()
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        app_label = "labs"
        ordering = ("room", "row_index", "col_index")
        constraints = [
            models.UniqueConstraint(
                fields=("room", "row_index", "col_index"),
                name="uniq_room_row_col",
            ),
            models.UniqueConstraint(
                fields=("room", "slot_code"),
                name="uniq_room_slot_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.room} / {self.slot_code}"
