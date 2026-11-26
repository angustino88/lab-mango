"""Gateway ingest of source readings into the latest value of each channel (proposal §6.8, §7.1).

Rules follow the proposal: the body never names a room, station, bench or equipment item; a reading is
attributed through its channel's binding at `observed_at`; a gateway only submits channels whose target sits
inside its scope; nothing is silently re-attributed. A channel that did not answer is stored with its status,
never as 0.

Race guard and idempotency: each channel's latest row is locked (`select_for_update`) and replaced only by a
newer observation; replaying a batch (same `sample_id`) reports `duplicate` and changes nothing. The raw
history (`TelemetryReading`, partitioned) and rollups are later steps of the proposal.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.labs.models.telemetry import (
    ChannelTargetBinding,
    GatewayScopeBinding,
    MetricDefinition,
    TelemetryChannel,
    TelemetryDevice,
    TelemetryDeviceRole,
    TelemetryDeviceState,
    TelemetryLatest,
    TelemetryReadingStatus,
    TelemetryTarget,
    TelemetryTargetType,
)

from ..exceptions import GatewayHasNoScope, GatewayNotRegistered
from ..queries.placement import resolve_placement
from .gateways import gateway_uid

FUTURE_TOLERANCE = timedelta(minutes=2)
MAX_AGE = timedelta(days=1)
MAX_OPERATIONS = 500

# Physical limits per metric, on top of each metric definition's own min/max.
_LIMITS: dict[str, tuple[Decimal | None, Decimal | None]] = {
    "temperature_c": (Decimal("-273.15"), None),
    "humidity_percent": (Decimal("0"), Decimal("100")),
    "power_w": (Decimal("0"), None),
}


@dataclass(frozen=True, slots=True)
class IngestReading:
    channel_id: int
    value: Decimal | None = None
    status: str = TelemetryReadingStatus.OK


@dataclass(frozen=True, slots=True)
class IngestOperation:
    device_uid: str
    sample_id: UUID
    observed_at: datetime
    readings: tuple[IngestReading, ...]


@dataclass(slots=True)
class OperationResult:
    status: str  # accepted | duplicate | partially_accepted | rejected
    errors: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IngestResult:
    results: list[OperationResult]
    config_version: int


def _within_scope(scope: GatewayScopeBinding, target: TelemetryTarget, placement) -> bool:
    scope_target = scope.target
    if scope_target.target_type == TelemetryTargetType.ROOM:
        return placement.room_id == scope_target.room_id
    if scope_target.target_type == TelemetryTargetType.STATION:
        return placement.station_id == scope_target.station_id
    return target.pk == scope_target.pk


def _value_error(metric: MetricDefinition, value: Decimal) -> bool:
    low, high = _LIMITS.get(metric.key, (None, None))
    bounds = [(low, high), (metric.value_min, metric.value_max)]
    return any((lo is not None and value < lo) or (hi is not None and value > hi) for lo, hi in bounds)


def ingest_samples(*, gateway_equipment_id: int, operations: list[IngestOperation]) -> IngestResult:
    """Apply a gateway's batch. Each operation is one source's poll cycle; readings are judged one by one."""
    if len(operations) > MAX_OPERATIONS:
        raise ValueError(f"At most {MAX_OPERATIONS} operations per batch.")
    now = timezone.now()
    gateway = TelemetryDevice.objects.filter(
        device_uid=gateway_uid(gateway_equipment_id),
        role=TelemetryDeviceRole.GATEWAY,
        state=TelemetryDeviceState.CLAIMED,
    ).first()
    if gateway is None:
        raise GatewayNotRegistered()
    scope = (
        GatewayScopeBinding.objects.select_related("target")
        .filter(gateway=gateway, valid_from__lte=now)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=now))
        .first()
    )
    if scope is None:
        raise GatewayHasNoScope()

    # Load everything the batch refers to in a fixed number of queries.
    uids = {operation.device_uid for operation in operations}
    sources = {
        device.device_uid: device
        for device in TelemetryDevice.objects.filter(device_uid__in=uids, role=TelemetryDeviceRole.SOURCE)
    }
    channel_ids = {reading.channel_id for operation in operations for reading in operation.readings}
    channels = {
        channel.pk: channel for channel in TelemetryChannel.objects.select_related("metric").filter(pk__in=channel_ids)
    }
    bindings: dict[int, list[ChannelTargetBinding]] = {}
    for item in ChannelTargetBinding.objects.select_related("target").filter(channel_id__in=channel_ids):
        bindings.setdefault(item.channel_id, []).append(item)
    placements = resolve_placement(target_ids={b.target_id for items in bindings.values() for b in items})

    results: list[OperationResult] = []
    seen_sources: set[int] = set()
    for operation in operations:
        source = sources.get(operation.device_uid)
        if source is None or source.state != TelemetryDeviceState.CLAIMED:
            results.append(OperationResult("rejected", [{"code": "source_not_claimed"}]))
            continue
        if not now - MAX_AGE <= operation.observed_at <= now + FUTURE_TOLERANCE:
            results.append(OperationResult("rejected", [{"code": "observed_at_out_of_range"}]))
            continue
        accepted = duplicates = 0
        errors: list[dict] = []
        for index, reading in enumerate(operation.readings):
            channel = channels.get(reading.channel_id)
            binding = next(
                (
                    item
                    for item in bindings.get(reading.channel_id, [])
                    if item.valid_from <= operation.observed_at
                    and (item.valid_to is None or item.valid_to > operation.observed_at)
                ),
                None,
            )
            if channel is None or channel.source_id != source.pk or not channel.is_enabled or binding is None:
                errors.append({"reading": index, "code": "channel_not_bound"})
                continue
            placement = placements.get(binding.target_id)
            if placement is None:
                errors.append({"reading": index, "code": "target_not_located"})
                continue
            if not _within_scope(scope, binding.target, placement):
                errors.append({"reading": index, "code": "outside_gateway_scope"})
                continue
            ok = reading.status == TelemetryReadingStatus.OK
            if ok and (reading.value is None or _value_error(channel.metric, reading.value)):
                errors.append({"reading": index, "code": "value_out_of_range"})
                continue
            outcome = _store_latest(
                channel=channel,
                target_id=binding.target_id,
                gateway=gateway,
                operation=operation,
                status=reading.status,
                value=reading.value if ok else None,
                received_at=now,
            )
            accepted += outcome == "stored"
            duplicates += outcome == "duplicate"
            if outcome == "older":
                accepted += 1  # valid, just not newer than what the dashboard already shows
        seen_sources.add(source.pk)
        total = len(operation.readings)
        if errors and not (accepted or duplicates):
            status = "rejected"
        elif errors:
            status = "partially_accepted"
        elif total and duplicates == total:
            status = "duplicate"
        else:
            status = "accepted"
        results.append(OperationResult(status, errors))

    if seen_sources:
        TelemetryDevice.objects.filter(pk__in=seen_sources | {gateway.pk}).update(last_seen_at=now)
    return IngestResult(results=results, config_version=gateway.config_version)


def _store_latest(*, channel, target_id, gateway, operation, status, value, received_at) -> str:
    """Replace the channel's latest reading only with a newer one. Returns stored | duplicate | older."""
    values = {
        "target_id": target_id,
        "metric_id": channel.metric_id,
        "gateway": gateway,
        "sample_id": operation.sample_id,
        "observed_at": operation.observed_at,
        "received_at": received_at,
        "status": status,
        "value": value,
    }
    with transaction.atomic():
        current = TelemetryLatest.objects.select_for_update().filter(channel=channel).first()
        if current is None:
            try:
                with transaction.atomic():
                    TelemetryLatest.objects.create(channel=channel, **values)
                return "stored"
            except IntegrityError:
                # A concurrent batch created the row first; judge against it.
                current = TelemetryLatest.objects.select_for_update().get(channel=channel)
        if current.sample_id == operation.sample_id and current.observed_at == operation.observed_at:
            return "duplicate"
        if current.observed_at >= operation.observed_at:
            return "older"
        for key, item in values.items():
            setattr(current, key, item)
        current.save()
        return "stored"
