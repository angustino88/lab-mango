from django.db import models

from core.labs.models.resource.equipment.equipment import Equipment


class PowerEquipment(Equipment):
    """Power equipment extension of the shared equipment record.

    Max voltage / max current are ProductModelSpecification values.
    """

    EQUIPMENT_CATEGORY_KEY = "power"

    channels = models.PositiveSmallIntegerField(null=True, blank=True)
    interface = models.ForeignKey(
        "labs.EquipmentInterface",
        related_name="%(app_label)s_%(class)s_interface",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    power_rating = models.PositiveIntegerField(
        null=True, blank=True, help_text="Output capacity in watts."
    )

    class Meta:
        app_label = "labs"
        indexes = [
            models.Index(fields=("channels",), name="power_channels_idx"),
            models.Index(fields=("power_rating",), name="power_rating_idx"),
        ]
