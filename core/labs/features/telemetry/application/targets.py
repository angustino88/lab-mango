"""Targets, placement checks and gateway config-version bumps shared by telemetry commands.

Race guards: target rows are created with the per-resource unique constraints and re-read on conflict, so
concurrent first uses converge on one row. Config-version bumps are single `UPDATE … SET n = n + 1`
statements (row locks), so concurrent changes never lose an increment.
"""

from collections.abc import Iterable
from typing import NoReturn

from django.db import IntegrityError, transaction
from django.db.models import F, Model, Q

from core.common.domain.errors import DetailMessage, ValidationFailed
from core.labs.features.telemetry.contracts import Placement, TargetRef
from core.labs.features.telemetry.exceptions import TargetNotFound, TargetNotLocated, TargetOutsideInstallRoom
from core.labs.features.telemetry.queries.placement import resolve_placement
from core.labs.models import Bench, Equipment, Room, Station
from core.labs.models.telemetry import GatewayScopeBinding, TelemetryDevice, TelemetryTarget, TelemetryTargetType

# Existence checks read other owners' live rows through their default managers (soft-deleted rows excluded).
RESOURCE_MODELS: dict[str, type[Model]] = {
    TelemetryTargetType.ROOM: Room,
    TelemetryTargetType.STATION: Station,
    TelemetryTargetType.BENCH: Bench,
    TelemetryTargetType.EQUIPMENT: Equipment,
}


def ensure_target(ref: TargetRef) -> TelemetryTarget:
    """The target row for a live resource, created on first use."""
    model = RESOURCE_MODELS.get(ref.type)
    if model is None or not model._default_manager.filter(pk=ref.id).exists():
        raise TargetNotFound()
    lookup = {f"{ref.type}_id": ref.id}
    target = TelemetryTarget.objects.filter(**lookup).first()
    if target is not None:
        return target
    try:
        with transaction.atomic():
            return TelemetryTarget.objects.create(target_type=ref.type, **lookup)
    except IntegrityError:
        return TelemetryTarget.objects.get(**lookup)


def require_placement(target: TelemetryTarget) -> Placement:
    placement = resolve_placement(target_ids=[target.pk]).get(target.pk)
    if placement is None:
        raise TargetNotLocated()
    return placement


def ensure_same_room(*, measured: TelemetryTarget, installed: TelemetryTarget) -> Placement:
    """A channel may only measure something in the room its source is installed in."""
    measured_placement = require_placement(measured)
    if measured_placement.room_id != require_placement(installed).room_id:
        raise TargetOutsideInstallRoom()
    return measured_placement


def bump_gateways(placements: Iterable[Placement | None]) -> None:
    """Increment the config version of every gateway whose current scope covers one of `placements`."""
    rooms = {placement.room_id for placement in placements if placement is not None}
    stations = {placement.station_id for placement in placements if placement is not None and placement.station_id}
    if not rooms and not stations:
        return
    gateway_ids = GatewayScopeBinding.objects.filter(
        Q(target__room_id__in=rooms) | Q(target__station_id__in=stations), valid_to__isnull=True
    ).values("gateway_id")
    TelemetryDevice.objects.filter(pk__in=gateway_ids).update(config_version=F("config_version") + 1)


def placement_of(target_id: int | None) -> Placement | None:
    if target_id is None:
        return None
    return resolve_placement(target_ids=[target_id]).get(target_id)


def raise_invalid(errors: dict[str, str]) -> NoReturn:
    """Field errors as a 422 with clean `field` paths (e.g. `modbus.port`), code `invalid` per field."""
    raise ValidationFailed(
        "Some fields are invalid.",
        details={field: DetailMessage(message, "invalid") for field, message in errors.items()},
    )


def constraint_name(error: IntegrityError) -> str | None:
    return getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)


__all__ = [
    "RESOURCE_MODELS",
    "bump_gateways",
    "constraint_name",
    "ensure_same_room",
    "ensure_target",
    "placement_of",
    "raise_invalid",
    "require_placement",
]
