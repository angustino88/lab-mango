"""Coordinator commands on device observations: link to inventory and expected devices."""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Q

from core.common.domain.errors import Conflict, NotFound, ValidationFailed
from core.labs.features.equipment.public import (
    RegisterHardwareIdInput,
    lock_monitoring_computing,
    match_hardware_ids,
    register_hardware_id,
)
from core.labs.models import Equipment
from core.labs.models.monitoring import DeviceConnection, ExpectedDevice

_MATCH_FIELDS = ("equipment", "interface", "match_status")


@dataclass(frozen=True, slots=True)
class LinkDeviceConnectionInput:
    connection_id: int
    equipment_id: int


@transaction.atomic
def link_device_connection(command: LinkDeviceConnectionInput, *, actor) -> int:
    """Register the observed device's hardware IDs on an inventory unit, then re-match its observations.

    ``Equipment.serial_number`` is never written: it is a human label. Race guard: the reporting
    computing unit's lock (the same parent lock ingestion takes), then the equipment row lock inside
    ``register_hardware_id``, then the projection rows. Safe to run twice: registering an ID the unit
    already holds is a no-op and re-matching is idempotent. Returns the connection id.
    """
    computing_id = (
        DeviceConnection.objects.filter(pk=command.connection_id).values_list("computing_id", flat=True).first()
    )
    if computing_id is None:
        raise NotFound("The device connection does not exist.")
    lock_monitoring_computing(computing_id)
    connection = DeviceConnection.objects.select_for_update().get(pk=command.connection_id)
    reported = [(item["kind"], item["value"]) for item in connection.hardware_ids or [] if item.get("value")]
    if not reported:
        raise Conflict("The observed device reported no hardware ID.", code="hardware_id_unavailable")
    for kind, value in reported:
        register_hardware_id(
            RegisterHardwareIdInput(command.equipment_id, kind, value, computing_id=computing_id), actor=actor
        )
    shares_an_id = Q()
    for kind, value in reported:
        shares_an_id |= Q(hardware_ids__contains=[{"kind": kind, "value": value}])
    rows = list(DeviceConnection.objects.select_for_update().filter(shares_an_id).order_by("pk"))
    for row_computing in {row.computing_id for row in rows}:
        scoped = [row for row in rows if row.computing_id == row_computing]
        evidence = {row.pk: (_ids(row), row.interface_name) for row in scoped}
        matches = match_hardware_ids(computing_id=row_computing, evidence=evidence.values())
        for row in scoped:
            match = matches[evidence[row.pk]]
            row.equipment_id, row.interface_id, row.match_status = match.equipment_id, match.interface_id, match.status
    DeviceConnection.objects.bulk_update(rows, _MATCH_FIELDS)
    return connection.pk


def _ids(row: DeviceConnection) -> tuple[tuple[str, str], ...]:
    return tuple((item["kind"], item["value"]) for item in row.hardware_ids or [])


@dataclass(frozen=True, slots=True)
class CreateExpectedDeviceInput:
    computing_id: int
    equipment_id: int
    notify_on_disconnect: bool = False


@transaction.atomic
def create_expected_device(command: CreateExpectedDeviceInput, *, actor) -> ExpectedDevice:
    """Race guard: ``expected_device_unique``; a duplicate returns 409, never a second row."""
    if command.computing_id == command.equipment_id:
        raise ValidationFailed("A computing unit cannot be expected on itself.")
    lock_monitoring_computing(command.computing_id)
    if not Equipment.objects.filter(pk=command.equipment_id, deleted_at__isnull=True).exists():
        raise NotFound("The equipment does not exist.")
    expected = ExpectedDevice(
        computing_id=command.computing_id,
        equipment_id=command.equipment_id,
        notify_on_disconnect=command.notify_on_disconnect,
    )
    try:
        with transaction.atomic():
            expected.save(actor=actor)
    except IntegrityError as error:
        raise Conflict(
            "This equipment is already expected on this computing unit.", code="expected_device_exists"
        ) from error
    return expected


@dataclass(frozen=True, slots=True)
class UpdateExpectedDeviceInput:
    expected_device_id: int
    notify_on_disconnect: bool


@transaction.atomic
def update_expected_device(command: UpdateExpectedDeviceInput, *, actor) -> ExpectedDevice:
    """Race guard: the expectation row lock. Setting the same value twice is a no-op save."""
    expected = ExpectedDevice.objects.select_for_update().filter(pk=command.expected_device_id).first()
    if expected is None:
        raise NotFound("The expected device does not exist.")
    expected.notify_on_disconnect = command.notify_on_disconnect
    expected.save(actor=actor, update_fields=("notify_on_disconnect", "modified"))
    return expected


@transaction.atomic
def delete_expected_device(*, expected_device_id: int, actor) -> None:
    """Idempotent at the database: deleting a missing row reports 404 and changes nothing."""
    deleted, _ = ExpectedDevice.objects.filter(pk=expected_device_id).delete()
    if not deleted:
        raise NotFound("The expected device does not exist.")


__all__ = (
    "CreateExpectedDeviceInput",
    "LinkDeviceConnectionInput",
    "UpdateExpectedDeviceInput",
    "create_expected_device",
    "delete_expected_device",
    "link_device_connection",
    "update_expected_device",
)
