"""Register and remove machine-read hardware IDs of equipment (coordinator commands).

Race guard: the ``Equipment`` row lock of the unit, then the partial unique constraints
``equipment_hardware_id_global_uniq`` / ``equipment_hardware_id_scoped_uniq``; a concurrent
registration of the same ID by another unit surfaces as ``Conflict``. Registering an ID the unit
already holds is a no-op, so the command is safe to run twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from core.common.domain.errors import Conflict, NotFound, ValidationFailed
from core.labs.models import ComputingProfile, Equipment
from core.labs.models.resource.equipment.hardware_id import (
    PORT_BOUND_PNP_ID_REGEX,
    EquipmentHardwareId,
    EquipmentHardwareIdKind,
)

MAX_VALUE_LENGTH = 512
_PORT_BOUND = re.compile(PORT_BOUND_PNP_ID_REGEX)


def normalize_hardware_id(kind: str, value: str) -> str:
    """Upper case, trimmed; PnP IDs use backslash separators (agents and Device Manager agree)."""
    value = (value or "").strip()
    if kind == EquipmentHardwareIdKind.PNP_ID:
        value = value.replace("/", "\\")
    return value.upper()


def is_port_bound(kind: str, value: str) -> bool:
    return kind == EquipmentHardwareIdKind.PNP_ID and bool(_PORT_BOUND.search(value))


@dataclass(frozen=True, slots=True)
class RegisterHardwareIdInput:
    equipment_id: int
    kind: str
    value: str
    computing_id: int | None = None


@transaction.atomic
def register_hardware_id(command: RegisterHardwareIdInput, *, actor) -> EquipmentHardwareId:
    if command.kind not in EquipmentHardwareIdKind.values:
        raise ValidationFailed("Unknown hardware ID kind.", details={"kind": "Unknown hardware ID kind."})
    value = normalize_hardware_id(command.kind, command.value)
    if not value or len(value) > MAX_VALUE_LENGTH:
        raise ValidationFailed(
            f"Enter a hardware ID of at most {MAX_VALUE_LENGTH} characters.",
            details={"value": f"Enter a hardware ID of at most {MAX_VALUE_LENGTH} characters."},
        )
    if command.kind == EquipmentHardwareIdKind.PNP_ID and "\\" not in value:
        raise ValidationFailed(
            "A PnP device ID looks like USB\\VID_xxxx&PID_xxxx\\….",
            details={"value": "A PnP device ID looks like USB\\VID_xxxx&PID_xxxx\\…."},
        )
    port_bound = is_port_bound(command.kind, value)
    computing_id = command.computing_id
    if port_bound and computing_id is None:
        raise ValidationFailed(
            "This PnP ID was generated from a USB port; choose the computer it was read on.",
            details={"computing_id": "This PnP ID was generated from a USB port; choose the computer it was read on."},
        )
    if not port_bound:
        computing_id = None  # a device-reported ID is valid on every computer
    equipment = Equipment.objects.select_for_update(of=("self",)).filter(pk=command.equipment_id).first()
    if equipment is None or equipment.deleted_at is not None:
        raise NotFound("The equipment does not exist.")
    if computing_id is not None:
        if computing_id == equipment.pk:
            raise ValidationFailed(
                "A unit cannot be scoped to itself.", details={"computing_id": "A unit cannot be scoped to itself."}
            )
        if not ComputingProfile.objects.filter(equipment_id=computing_id, equipment__deleted_at__isnull=True).exists():
            raise ValidationFailed("Choose a computing unit.", details={"computing_id": "Choose a computing unit."})
    existing = EquipmentHardwareId.objects.filter(kind=command.kind, value=value, computing_id=computing_id).first()
    if existing is not None:
        if existing.equipment_id == equipment.pk:
            return existing
        raise Conflict("This hardware ID is registered on another unit.", code="hardware_id_in_use")
    record = EquipmentHardwareId(equipment=equipment, kind=command.kind, value=value, computing_id=computing_id)
    try:
        with transaction.atomic():
            record.save(actor=actor)
    except IntegrityError as error:
        raise Conflict("This hardware ID is registered on another unit.", code="hardware_id_in_use") from error
    return record


@transaction.atomic
def delete_hardware_id(*, equipment_id: int, hardware_id_id: int, actor) -> None:
    """Idempotent at the database: a missing row reports 404 and changes nothing."""
    deleted, _ = EquipmentHardwareId.objects.filter(pk=hardware_id_id, equipment_id=equipment_id).delete()
    if not deleted:
        raise NotFound("The hardware ID does not exist.")


__all__ = (
    "RegisterHardwareIdInput",
    "delete_hardware_id",
    "is_port_bound",
    "normalize_hardware_id",
    "register_hardware_id",
)
