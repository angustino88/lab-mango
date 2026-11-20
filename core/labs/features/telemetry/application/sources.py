"""Register, claim, update and retire sources (devices a gateway reads).

Race guards: the device row is locked for every change; uniqueness of the device UID, the equipment link and
the Modbus `(network_host, port)` are database constraints mapped to stable errors. Idempotency: retiring a
retired device returns it unchanged; a repeated registration meets the unique device UID and is refused.
"""

import ipaddress
import re
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.telemetry.contracts import TargetRef
from core.labs.features.telemetry.exceptions import (
    ChannelsStillBound,
    DeviceAlreadyRegistered,
    DeviceStateConflict,
    ModbusAddressInUse,
)
from core.labs.models import Equipment
from core.labs.models.telemetry import (
    SOURCE_KINDS,
    ChannelTargetBinding,
    ModbusFraming,
    ModbusSourceSettings,
    SerialInterface,
    SerialParity,
    TelemetryDevice,
    TelemetryDeviceKind,
    TelemetryDeviceRole,
    TelemetryDeviceState,
)

from .targets import bump_gateways, constraint_name, ensure_target, placement_of, raise_invalid, require_placement

_MAC = re.compile(r"^[0-9A-F]{2}([:-]?[0-9A-F]{2}){5}$")
_HOST = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


@dataclass(frozen=True, slots=True)
class ModbusSettingsInput:
    network_host: str
    port: int = 502
    framing: str = ModbusFraming.MBAP
    serial_interface: str = SerialInterface.NONE
    baud_rate: int | None = None
    parity: str = ""
    data_bits: int | None = None
    stop_bits: int | None = None
    request_timeout_ms: int = 800
    serialize_requests: bool = True


@dataclass(frozen=True, slots=True)
class RegisterSourceInput:
    kind: str
    device_uid: str
    equipment_id: int
    installed_at: TargetRef
    modbus: ModbusSettingsInput | None = None
    manufacturer: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class ClaimSourceInput:
    device_id: int
    equipment_id: int
    installed_at: TargetRef
    modbus: ModbusSettingsInput | None = None
    manufacturer: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class UpdateSourceInput:
    device_id: int
    installed_at: TargetRef | None = None
    modbus: ModbusSettingsInput | None = None
    manufacturer: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class RetireDeviceInput:
    device_id: int


def normalize_device_uid(value: str) -> str:
    """MAC addresses become `AA:BB:CC:DD:EE:FF`; other identifiers (serials) are trimmed."""
    cleaned = (value or "").strip()
    if _MAC.match(cleaned.upper()):
        digits = re.sub(r"[:-]", "", cleaned.upper())
        return ":".join(digits[index : index + 2] for index in range(0, 12, 2))
    return cleaned


def _modbus_errors(settings: ModbusSettingsInput) -> dict[str, str]:
    errors: dict[str, str] = {}
    host = (settings.network_host or "").strip()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST.match(host):
            errors["modbus.network_host"] = "Enter an IP address or host name."
    if not 1 <= settings.port <= 65535:
        errors["modbus.port"] = "Use a port between 1 and 65535."
    if settings.framing not in ModbusFraming.values:
        errors["modbus.framing"] = "Select mbap or rtu_over_tcp."
    if not 50 <= settings.request_timeout_ms <= 30000:
        errors["modbus.request_timeout_ms"] = "Use 50-30000 ms."
    serial = (settings.baud_rate, settings.parity, settings.data_bits, settings.stop_bits)
    if settings.serial_interface == SerialInterface.NONE:
        if any(value not in (None, "") for value in serial):
            errors["modbus.serial_interface"] = "Select RS485 or RS232 when serial settings are given."
    elif settings.serial_interface not in SerialInterface.values:
        errors["modbus.serial_interface"] = "Select rs485, rs232 or none."
    else:
        if settings.baud_rate is None or settings.baud_rate < 300:
            errors["modbus.baud_rate"] = "Enter the bus baud rate (e.g. 9600)."
        if settings.parity not in SerialParity.values:
            errors["modbus.parity"] = "Select N, E or O."
        if settings.data_bits not in (7, 8):
            errors["modbus.data_bits"] = "Select 7 or 8."
        if settings.stop_bits not in (1, 2):
            errors["modbus.stop_bits"] = "Select 1 or 2."
    return errors


def _validate(*, kind: str, device_uid: str | None, equipment_id: int | None, modbus: ModbusSettingsInput | None):
    errors: dict[str, str] = {}
    if kind not in SOURCE_KINDS:
        errors["kind"] = f"Select one of: {', '.join(SOURCE_KINDS)}."
    if device_uid is not None and not device_uid:
        errors["device_uid"] = "Enter the device MAC address or serial number."
    if equipment_id is not None and not Equipment.objects.filter(pk=equipment_id).exists():
        errors["equipment_id"] = "Select an existing equipment item."
    if kind == TelemetryDeviceKind.MODBUS_TCP:
        if modbus is None:
            errors["modbus"] = "Modbus TCP devices need an address and port."
        else:
            errors.update(_modbus_errors(modbus))
    if errors:
        raise_invalid(errors)


def _save_modbus(device: TelemetryDevice, settings: ModbusSettingsInput) -> None:
    values = {
        "network_host": settings.network_host.strip(),
        "port": settings.port,
        "framing": settings.framing,
        "serial_interface": settings.serial_interface,
        "baud_rate": settings.baud_rate,
        "parity": settings.parity,
        "data_bits": settings.data_bits,
        "stop_bits": settings.stop_bits,
        "request_timeout_ms": settings.request_timeout_ms,
        "serialize_requests": settings.serialize_requests,
    }
    try:
        with transaction.atomic():
            ModbusSourceSettings.objects.update_or_create(device=device, defaults=values)
    except IntegrityError as error:
        if constraint_name(error) == "telemetry_modbus_address_uniq":
            raise ModbusAddressInUse() from error
        raise


def _save_device(device: TelemetryDevice, *, actor) -> None:
    try:
        with transaction.atomic():
            device.save(actor=actor)
    except IntegrityError as error:
        raise DeviceAlreadyRegistered() from error


def _lock_source(device_id: int) -> TelemetryDevice:
    device = TelemetryDevice.objects.select_for_update().get(pk=device_id)
    if device.role != TelemetryDeviceRole.SOURCE:
        raise DeviceStateConflict("This device is a gateway, not a source.")
    return device


@transaction.atomic
def register_source(command: RegisterSourceInput, *, actor) -> TelemetryDevice:
    """Register a source by its label UID directly as claimed (installed, linked to its asset)."""
    device_uid = normalize_device_uid(command.device_uid)
    _validate(kind=command.kind, device_uid=device_uid, equipment_id=command.equipment_id, modbus=command.modbus)
    installed_at = ensure_target(command.installed_at)
    placement = require_placement(installed_at)
    device = TelemetryDevice(
        role=TelemetryDeviceRole.SOURCE,
        kind=command.kind,
        device_uid=device_uid,
        equipment_id=command.equipment_id,
        installed_at=installed_at,
        state=TelemetryDeviceState.CLAIMED,
        manufacturer=command.manufacturer.strip(),
        model=command.model.strip(),
    )
    _save_device(device, actor=actor)
    if command.modbus is not None:
        _save_modbus(device, command.modbus)
    bump_gateways([placement])
    return device


@transaction.atomic
def claim_source(command: ClaimSourceInput, *, actor) -> TelemetryDevice:
    """Turn a discovered source into a claimed one: link its asset, install location and settings."""
    device = _lock_source(command.device_id)
    if device.state != TelemetryDeviceState.DISCOVERED:
        raise DeviceStateConflict("Only a discovered device can be claimed.")
    _validate(kind=device.kind, device_uid=None, equipment_id=command.equipment_id, modbus=command.modbus)
    installed_at = ensure_target(command.installed_at)
    placement = require_placement(installed_at)
    device.equipment_id = command.equipment_id
    device.installed_at = installed_at
    device.state = TelemetryDeviceState.CLAIMED
    device.manufacturer = command.manufacturer.strip() or device.manufacturer
    device.model = command.model.strip() or device.model
    _save_device(device, actor=actor)
    if command.modbus is not None:
        _save_modbus(device, command.modbus)
    bump_gateways([placement])
    return device


@transaction.atomic
def update_source(command: UpdateSourceInput, *, actor) -> TelemetryDevice:
    """Change a claimed source's install location, connection settings or descriptive fields."""
    device = _lock_source(command.device_id)
    if device.state != TelemetryDeviceState.CLAIMED:
        raise DeviceStateConflict("Only a claimed device can be changed.")
    if command.modbus is not None:
        _validate(kind=device.kind, device_uid=None, equipment_id=None, modbus=command.modbus)
    old_placement = placement_of(device.installed_at_id)
    new_placement = old_placement
    if command.installed_at is not None:
        installed_at = ensure_target(command.installed_at)
        new_placement = require_placement(installed_at)
        if old_placement is not None and new_placement.room_id != old_placement.room_id:
            if ChannelTargetBinding.objects.filter(channel__source=device, valid_to__isnull=True).exists():
                raise ChannelsStillBound()
        device.installed_at = installed_at
    if command.manufacturer is not None:
        device.manufacturer = command.manufacturer.strip()
    if command.model is not None:
        device.model = command.model.strip()
    _save_device(device, actor=actor)
    if command.modbus is not None:
        _save_modbus(device, command.modbus)
    bump_gateways([old_placement, new_placement])
    return device


@transaction.atomic
def retire_device(command: RetireDeviceInput, *, actor) -> TelemetryDevice:
    """Retire a gateway or source: its bindings end now and its connection settings are released."""
    device = TelemetryDevice.objects.select_for_update().get(pk=command.device_id)
    if device.state == TelemetryDeviceState.RETIRED:
        return device
    now = timezone.now()
    placements = [placement_of(device.installed_at_id)]
    if device.role == TelemetryDeviceRole.GATEWAY:
        device.scope_bindings.filter(valid_to__isnull=True).update(valid_to=now)
    else:
        ChannelTargetBinding.objects.filter(channel__source=device, valid_to__isnull=True).update(valid_to=now)
        ModbusSourceSettings.objects.filter(device=device).delete()
    device.state = TelemetryDeviceState.RETIRED
    device.save(actor=actor, update_fields=["state", "modified", "last_modified_by"])
    bump_gateways(placements)
    return device


__all__ = [
    "ClaimSourceInput",
    "ModbusSettingsInput",
    "RegisterSourceInput",
    "RetireDeviceInput",
    "UpdateSourceInput",
    "claim_source",
    "normalize_device_uid",
    "register_source",
    "retire_device",
    "update_source",
]
