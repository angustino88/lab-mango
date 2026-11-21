"""Pure telemetry policies: commands gather the facts, these functions decide."""

from core.labs.features.telemetry.exceptions import GatewayKindMismatch, ProfileApprovalForbidden
from core.labs.models.telemetry import TelemetryDeviceKind, TelemetryTargetType

SCOPE_TYPE_BY_GATEWAY_KIND: dict[str, str] = {
    TelemetryDeviceKind.ROOM_HOST: TelemetryTargetType.ROOM,
    TelemetryDeviceKind.STATION_PC: TelemetryTargetType.STATION,
    TelemetryDeviceKind.EQUIPMENT_AGENT: TelemetryTargetType.EQUIPMENT,
}


def ensure_scope_fits_gateway(*, gateway_kind: str, target_type: str) -> None:
    if SCOPE_TYPE_BY_GATEWAY_KIND.get(gateway_kind) != target_type:
        raise GatewayKindMismatch()


def ensure_can_approve_profiles(*, may_approve_profiles: bool) -> None:
    if not may_approve_profiles:
        raise ProfileApprovalForbidden()


__all__ = ["SCOPE_TYPE_BY_GATEWAY_KIND", "ensure_can_approve_profiles", "ensure_scope_fits_gateway"]
