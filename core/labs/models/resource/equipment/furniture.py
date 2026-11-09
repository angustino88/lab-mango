from django.db import models

from core.labs.models.resource.equipment.equipment import Equipment


class FurnitureEquipment(Equipment):
    EQUIPMENT_CATEGORY_KEY = "furniture"

    dimensions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Keys length_mm, width_mm, height_mm.",
    )
    material = models.ForeignKey(
        "labs.Material",
        related_name="%(app_label)s_%(class)s_material",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        app_label = "labs"
