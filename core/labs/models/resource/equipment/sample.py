
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.equipment.equipment import Equipment


class SampleCustomer(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(
                fields=("name",),
                opclasses=("gin_trgm_ops",),
                name="sample_customer_name_idx",
            ),
        ]


class SampleCharacteristic(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(
                fields=("name",),
                opclasses=("gin_trgm_ops",),
                name="sample_characteristic_name_idx",
            ),
        ]


class SampleEquipment(Equipment):
    EQUIPMENT_CATEGORY_KEY = "sample"

    customer = models.ForeignKey(
        "labs.SampleCustomer",
        related_name="%(app_label)s_%(class)s_customer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    interfaces = models.ManyToManyField(
        "labs.EquipmentInterface",
        related_name="%(app_label)s_%(class)s_interfaces",
        blank=True,
    )
    characteristics = models.ManyToManyField(
        "labs.SampleCharacteristic",
        related_name="%(app_label)s_%(class)s_characteristics",
        blank=True,
    )
    class Meta:
        app_label = "labs"
