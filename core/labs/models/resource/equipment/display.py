from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.equipment.equipment import Equipment


class DisplaySize(TimeStampedModel, UserStampedModel):
    size = models.CharField(max_length=255, unique=True, help_text="Label shown in the select, e.g. 27\".")
    diagonal_in = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, unique=True, help_text="Diagonal in inches."
    )

    def __str__(self) -> str:
        return self.size

    class Meta:
        app_label = "labs"
        ordering = ("size",)
        indexes = [
            GinIndex(
                fields=("size",),
                opclasses=("gin_trgm_ops",),
                name="display_size_idx",
            ),
        ]


class DisplayResolution(TimeStampedModel, UserStampedModel):
    resolution = models.CharField(max_length=255, unique=True, help_text="Label shown in the select, e.g. QHD.")
    width_px = models.PositiveSmallIntegerField(null=True, blank=True)
    height_px = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return self.resolution

    class Meta:
        app_label = "labs"
        ordering = ("resolution",)
        constraints = [
            models.UniqueConstraint(
                fields=("width_px", "height_px"),
                condition=models.Q(width_px__isnull=False, height_px__isnull=False),
                name="display_resolution_pixels_uniq",
            ),
        ]
        indexes = [
            GinIndex(
                fields=("resolution",),
                opclasses=("gin_trgm_ops",),
                name="display_resolution_idx",
            ),
        ]


class DisplayEquipment(Equipment):
    EQUIPMENT_CATEGORY_KEY = "display"

    size = models.ForeignKey(
        "labs.DisplaySize",
        related_name="%(app_label)s_%(class)s_size",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    resolution = models.ForeignKey(
        "labs.DisplayResolution",
        related_name="%(app_label)s_%(class)s_resolution",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    interfaces = models.ManyToManyField(
        "labs.EquipmentInterface",
        related_name="%(app_label)s_%(class)s_interfaces",
        blank=True,
    )

    class Meta:
        app_label = "labs"
