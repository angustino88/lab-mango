"""Record a serial number observed by a computing agent on an inventory unit."""

from django.db import transaction

from core.common.domain.errors import Conflict, NotFound
from core.labs.models import Equipment

from .update_equipment import UpdateEquipmentInput, update_equipment


@transaction.atomic
def claim_equipment_serial(*, equipment_id: int, serial_number: str, actor) -> None:
    """Give an active unit the observed serial number, or confirm it already has it.

    Race guard: the ``Equipment`` row lock (taken here and again, reentrantly, by
    ``update_equipment``). A unit that already holds a different serial is never
    overwritten: that is an inventory correction, not a link. Serials are not unique in the
    schema (inventory may legitimately hold duplicates), so a serial already held by another
    active unit is refused here; a concurrent claim of the same serial can still create a
    duplicate, which matching then reports as ambiguous rather than guessing.
    """
    serial_number = serial_number.strip()
    if not serial_number:
        raise Conflict("The observed device reported no serial number.", code="serial_unavailable")
    current = (
        Equipment.objects.select_for_update(of=("self",))
        .filter(pk=equipment_id, deleted_at__isnull=True)
        .values_list("serial_number", flat=True)
        .first()
    )
    if current is None:
        raise NotFound("The equipment does not exist.")
    if current == serial_number:
        return
    if (
        Equipment.objects.filter(serial_number=serial_number, deleted_at__isnull=True)
        .exclude(pk=equipment_id)
        .exists()
    ):
        raise Conflict(
            "Another active unit already has this serial number; resolve the duplicate first.",
            code="equipment_serial_in_use",
        )
    if current:
        raise Conflict(
            "This equipment already has a different serial number; correct it in the inventory first.",
            code="equipment_serial_conflict",
        )
    update_equipment(UpdateEquipmentInput(equipment_id, (("serial_number", serial_number),)), actor=actor)


__all__ = ("claim_equipment_serial",)
