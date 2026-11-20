"""Register gateways and set their scope.

Race guards: the gateway row is locked before its scope changes; one scope per gateway and one room
gateway per room are exclusion constraints (`telemetry_scope_one_per_gateway`, `telemetry_scope_one_room_host`).
Idempotency: registering the same equipment again returns the existing gateway; binding the current scope
again returns the open binding.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.telemetry.contracts import TargetRef
from core.labs.features.telemetry.exceptions import DeviceAlreadyRegistered, DeviceStateConflict, RoomGatewayExists
from core.labs.models import Equipment
from core.labs.models.telemetry import (
    GATEWAY_KINDS,
    GatewayScopeBinding,
    TelemetryDevice,
    TelemetryDeviceRole,
    TelemetryDeviceState,
)

from .policies import ensure_scope_fits_gateway
from .targets import constraint_name, ensure_target, raise_invalid, require_placement


@dataclass(frozen=True, slots=True)
class RegisterGatewayInput:
    equipment_id: int
    kind: str


@dataclass(frozen=True, slots=True)
class BindGatewayScopeInput:
    gateway_id: int
    target: TargetRef


def gateway_uid(equipment_id: int) -> str:
    """Gateways are keyed by their equipment, which agent authentication already resolves."""
    return f"equipment-{equipment_id}"


@transaction.atomic
def register_gateway(command: RegisterGatewayInput, *, actor) -> TelemetryDevice:
    """Register an enrolled PC (an equipment asset) as a telemetry gateway of `kind`."""
    if command.kind not in GATEWAY_KINDS:
        raise_invalid({"kind": f"Select one of: {', '.join(GATEWAY_KINDS)}."})
    if not Equipment.objects.filter(pk=command.equipment_id).exists():
        raise_invalid({"equipment_id": "Select an existing equipment item."})
    existing = TelemetryDevice.objects.select_for_update().filter(device_uid=gateway_uid(command.equipment_id)).first()
    if existing is not None:
        if existing.kind != command.kind or existing.state == TelemetryDeviceState.RETIRED:
            raise DeviceAlreadyRegistered()
        return existing
    gateway = TelemetryDevice(
        role=TelemetryDeviceRole.GATEWAY,
        kind=command.kind,
        device_uid=gateway_uid(command.equipment_id),
        equipment_id=command.equipment_id,
        state=TelemetryDeviceState.CLAIMED,
    )
    try:
        with transaction.atomic():
            gateway.save(actor=actor)
    except IntegrityError as error:
        raise DeviceAlreadyRegistered() from error
    return gateway


@transaction.atomic
def bind_gateway_scope(command: BindGatewayScopeInput, *, actor) -> GatewayScopeBinding:
    """Make the gateway cover `target` from now on; its previous scope ends now."""
    gateway = TelemetryDevice.objects.select_for_update().get(pk=command.gateway_id)
    if gateway.role != TelemetryDeviceRole.GATEWAY or gateway.state != TelemetryDeviceState.CLAIMED:
        raise DeviceStateConflict()
    ensure_scope_fits_gateway(gateway_kind=gateway.kind, target_type=command.target.type)
    target = ensure_target(command.target)
    require_placement(target)
    current = gateway.scope_bindings.filter(valid_to__isnull=True).first()
    if current is not None and current.target_id == target.pk:
        return current
    now = timezone.now()
    if current is not None:
        current.valid_to = now
        current.save(actor=actor, update_fields=["valid_to", "modified"])
    binding = GatewayScopeBinding(gateway=gateway, gateway_kind=gateway.kind, target=target, valid_from=now)
    try:
        with transaction.atomic():
            binding.save(actor=actor)
    except IntegrityError as error:
        if constraint_name(error) == "telemetry_scope_one_room_host":
            raise RoomGatewayExists() from error
        raise
    gateway.config_version += 1
    gateway.save(actor=actor, update_fields=["config_version", "modified"])
    return binding


__all__ = ["BindGatewayScopeInput", "RegisterGatewayInput", "bind_gateway_scope", "gateway_uid", "register_gateway"]
