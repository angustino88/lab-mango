
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.equipment.equipment import MAC_ADDRESS_VALIDATOR, Equipment


class NetworkingProtocol(TimeStampedModel, UserStampedModel):
    name = models.CharField(max_length=25, unique=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("name",)
        indexes = [
            GinIndex(
                fields=("name",),
                opclasses=("gin_trgm_ops",),
                name="networking_protocol_idx",
            ),
        ]


class NetworkingEquipment(Equipment):
    """Networking equipment (switch, router, bus interface).

    Channels, ports, CAN FD support etc. are ProductModelSpecification values;
    the firmware version is on Equipment.
    """

    EQUIPMENT_CATEGORY_KEY = "networking"

    protocol = models.ForeignKey(
        "labs.NetworkingProtocol",
        related_name="%(app_label)s_%(class)s_protocol",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    mac_address = models.CharField(max_length=17, blank=True, default="", validators=[MAC_ADDRESS_VALIDATOR])

    class Meta:
        app_label = "labs"
