"""Machine-read identity of an equipment unit, registered once by a coordinator.

``Equipment.serial_number`` is typed by people (part numbers, labels) and is never used to recognise
hardware. What an agent can read is stored here instead:

* ``pnp_id``: the Windows PnP device instance ID (Device Manager → Details → *Device instance path*),
  e.g. ``USB\\VID_1248&PID_1073\\007113-585343``. When its last segment contains ``&`` Windows built
  it from the USB port, so it is only valid on one computer and ``computing`` is required.
* ``vector_device``: the Vector device name license tools report as the license carrier
  (Vector License Client ``DeviceName``), e.g. ``007113-585343``.

Values are stored normalised (upper case, ``\\`` separators), so uniqueness ignores case.
"""

from django.db import models
from django.db.models import F, Q
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel

PORT_BOUND_PNP_ID_REGEX = r"\\[^\\]*&[^\\]*$"  # last path segment contains "&"


class EquipmentHardwareIdKind(models.TextChoices):
    PNP_ID = "pnp_id", "PnP device ID"
    VECTOR_DEVICE = "vector_device", "Vector device name"


class EquipmentHardwareId(TimeStampedModel, UserStampedModel):
    equipment = models.ForeignKey("labs.Equipment", related_name="hardware_ids", on_delete=models.CASCADE)
    kind = models.CharField(max_length=24, choices=EquipmentHardwareIdKind.choices)
    value = models.CharField(max_length=512, help_text="Normalised: upper case, backslash separators.")
    computing = models.ForeignKey(
        "labs.Equipment",
        null=True,
        blank=True,
        related_name="scoped_hardware_ids",
        on_delete=models.PROTECT,
        help_text="Only for IDs valid on one computer (port-bound PnP IDs): that computing unit.",
    )

    class Meta:
        app_label = "labs"
        ordering = ("equipment_id", "kind", "value")
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "value"),
                condition=Q(computing__isnull=True),
                name="equipment_hardware_id_global_uniq",
            ),
            models.UniqueConstraint(
                fields=("kind", "value", "computing"),
                condition=Q(computing__isnull=False),
                name="equipment_hardware_id_scoped_uniq",
            ),
            models.CheckConstraint(condition=~Q(value=""), name="equipment_hardware_id_value_not_empty"),
            models.CheckConstraint(
                condition=Q(kind__in=EquipmentHardwareIdKind.values), name="equipment_hardware_id_valid_kind"
            ),
            models.CheckConstraint(
                condition=~(
                    Q(kind=EquipmentHardwareIdKind.PNP_ID)
                    & Q(value__regex=PORT_BOUND_PNP_ID_REGEX)
                    & Q(computing__isnull=True)
                ),
                name="equipment_hardware_id_port_bound_scoped",
            ),
            models.CheckConstraint(condition=~Q(computing=F("equipment")), name="equipment_hardware_id_not_self"),
        ]
        indexes = [models.Index(fields=("kind", "value"), name="equipment_hardware_id_lookup")]

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"
