from django.db import models

from core.labs.models.resource.equipment.equipment import Equipment


class InstrumentEquipment(Equipment):
    """Laboratory instrument equipment.

    Calibration history is generic (ResourceServiceRecord); channels, bandwidth and
    similar technical data are ProductModelSpecification values.
    """

    EQUIPMENT_CATEGORY_KEY = "instrument"

    interfaces = models.ManyToManyField(
        "labs.EquipmentInterface",
        related_name="%(app_label)s_%(class)s_instruments",
        blank=True,
    )

    class Meta:
        app_label = "labs"
