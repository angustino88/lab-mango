"""Shared lookup tables used by several equipment categories."""

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class EquipmentInterface(TimeStampedModel, UserStampedModel):
    """Connection interface (USB, Ethernet, CAN, JTAG ...) for any equipment category.

    Replaces the former per-category tables DisplayInterface, InstrumentInterface,
    PowerInterface and SampleInterface, which all had the same shape.
    """

    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="equipment_interface_idx"),
        ]


class Material(TimeStampedModel, UserStampedModel):
    """Material of mechanical equipment and furniture (replaces two identical tables)."""

    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(fields=("name",), opclasses=("gin_trgm_ops",), name="material_name_idx"),
        ]
