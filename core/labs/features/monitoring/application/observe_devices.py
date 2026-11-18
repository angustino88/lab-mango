"""Atomic, ordered observation ingestion. Caller holds equipment then agent identity.

Race guard: equipment parent lock, cursor lock, plus DB batch/sequence/connection
uniqueness. Lock order: equipment -> authenticated identity -> cursor -> projections.
No network side effects. Replay is content-addressed and never refreshes freshness.

Ordering: within one generation a collector's applied sequences are contiguous for
incremental batches. A complete snapshot may skip ahead (it is self-contained); an
incremental batch that skips ahead is refused with ``snapshot_required`` so a lost or
delayed delta can never be silently dropped. Older sequences are acknowledged as stale.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid5

from django.db import transaction
from django.utils import timezone

from core.common.contracts import ActorContext
from core.common.db.idempotency import try_claim_operation
from core.common.domain.errors import Forbidden, ValidationFailed
from core.labs.features.equipment.public import lock_monitoring_computing, match_hardware_ids
from core.labs.features.monitoring.application.alerts import notify_expected_disconnects
from core.labs.features.monitoring.contracts import (
    DISCOVERY_COLLECTOR_KEY,
    DeviceObservationInput,
    ObservationAcknowledgment,
)
from core.labs.features.monitoring.exceptions import (
    ObservationConflict,
    ObservationInProgress,
    ObservationKeyReuse,
    ObservationSnapshotRequired,
)
from core.labs.models.monitoring import (
    DeviceConnection,
    DeviceConnectionState,
    DeviceObservationBatch,
    DeviceObservationCursor,
    MonitoringEvent,
    MonitoringEventAction,
)

MAX_DEVICES_PER_COLLECTOR = 200
MAX_SEQUENCE = 9007199254740991  # 2**53 - 1: exact in JSON numbers on every client.
MAX_CLOCK_SKEW = timedelta(minutes=5)
_PROJECTION_FIELDS = (
    "equipment",
    "interface",
    "match_status",
    "generation_key",
    "sequence",
    "name",
    "serial_number",
    "hardware_ids",
    "interface_name",
    "state",
    "observed_at",
    "received_at",
)


def observation_operation_scope(*, computing_id: int, generation_key: UUID, batch_key: UUID) -> bytes:
    """Advisory-claim scope shared by every caller that reports one batch.

    PostgreSQL advisory locks are reentrant per session, so an adapter may claim the
    same scope before taking its own locks and then call :func:`observe_devices`.
    """
    return f"POST:/agent/device-observations/actions/report:{computing_id}:{generation_key}:{batch_key}".encode()


def _validate(command: DeviceObservationInput) -> None:
    if not 1 <= command.sequence <= MAX_SEQUENCE or len(command.devices) > MAX_DEVICES_PER_COLLECTOR:
        raise ValidationFailed("Sequence or device count exceeds the observation limits.")
    if not timezone.is_aware(command.collected_at) or command.collected_at > timezone.now() + MAX_CLOCK_SKEW:
        raise ValidationFailed("Collection time must be timezone-aware and not more than five minutes in the future.")
    keys = [device.observation_key for device in command.devices]
    if len(keys) != len(set(keys)):
        raise ValidationFailed("Observation keys must be unique within a snapshot.")
    for device in command.devices:
        if device.state not in DeviceConnectionState.values or not device.observation_key or not device.interface_name:
            raise ValidationFailed("Each device needs a key, interface name and valid observed state.")


def _content_hash(command: DeviceObservationInput) -> str:
    canonical = json.dumps(asdict(command), default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _ack(batch: DeviceObservationBatch, *, replayed: bool = False) -> ObservationAcknowledgment:
    return ObservationAcknowledgment(
        batch.batch_key, batch.sequence, "applied" if batch.is_applied else "stale", batch.received_at, replayed
    )


def _disposition(command: DeviceObservationInput, cursor: DeviceObservationCursor | None) -> bool:
    """Return whether the batch applies; raise when the collector needs a full snapshot."""
    needs_snapshot = cursor is None or cursor.generation_key != command.generation_key or not cursor.is_current
    if needs_snapshot:
        if not command.is_complete:
            raise ObservationSnapshotRequired(
                "A complete snapshot is required for this collector and enrollment generation."
            )
        return True
    assert cursor is not None
    if command.sequence <= cursor.sequence:
        return False
    if not command.is_complete and command.sequence != cursor.sequence + 1:
        raise ObservationSnapshotRequired(
            f"Incremental batches must continue from sequence {cursor.sequence}; send a complete snapshot."
        )
    return True


def observe_devices(command: DeviceObservationInput, *, actor: ActorContext) -> ObservationAcknowledgment:
    if command.computing_id not in actor.equipment_ids or "monitoring:report" not in actor.capabilities:
        raise Forbidden("The principal cannot report for this computing equipment.")
    _validate(command)
    content_hash = _content_hash(command)
    with transaction.atomic():
        scope = observation_operation_scope(
            computing_id=command.computing_id, generation_key=command.generation_key, batch_key=command.batch_key
        )
        if not try_claim_operation(scope):
            raise ObservationInProgress("This request is still running.")
        # Reentrant when called by the authenticated agent workflow. Also protects
        # internal callers against cursor creation races.
        lock_monitoring_computing(command.computing_id)
        replay = DeviceObservationBatch.objects.filter(
            computing_id=command.computing_id, generation_key=command.generation_key, batch_key=command.batch_key
        ).first()
        if replay:
            if replay.content_hash != content_hash:
                raise ObservationKeyReuse("This idempotency key was already used with different content.")
            return _ack(replay, replayed=True)
        if DeviceObservationBatch.objects.filter(
            computing_id=command.computing_id,
            generation_key=command.generation_key,
            collector_key=command.collector_key,
            sequence=command.sequence,
        ).exists():
            raise ObservationConflict("This sequence was already used by another batch.")
        cursor = (
            DeviceObservationCursor.objects.select_for_update()
            .filter(computing_id=command.computing_id, collector_key=command.collector_key)
            .first()
        )
        is_applied = _disposition(command, cursor)
        received_at = timezone.now()
        batch = DeviceObservationBatch.objects.create(
            computing_id=command.computing_id,
            generation_key=command.generation_key,
            batch_key=command.batch_key,
            collector_key=command.collector_key,
            sequence=command.sequence,
            content_hash=content_hash,
            is_applied=is_applied,
            received_at=received_at,
        )
        if not is_applied:
            return _ack(batch)
        detached_equipment = _apply_projection(command, received_at=received_at)
        DeviceObservationCursor.objects.update_or_create(
            computing_id=command.computing_id,
            collector_key=command.collector_key,
            defaults={
                "generation_key": command.generation_key,
                "sequence": command.sequence,
                "is_current": True,
                "last_collected_at": command.collected_at,
                "last_received_at": received_at,
            },
        )
        MonitoringEvent.objects.create(
            # MonitoringEvent predates this feature and keeps its deployed field name.
            computer_id=command.computing_id,
            agent_id=command.agent_key,
            event_id=uuid5(command.generation_key, str(command.batch_key)),
            action=MonitoringEventAction.INVENTORY_SNAPSHOT,
            subject_type="device_connections",
            subject_id=command.collector_key,
            occurred_at=command.collected_at,
            reported_at=received_at,
            payload={
                "collector_key": command.collector_key,
                "sequence": command.sequence,
                "is_complete": command.is_complete,
                "devices": [asdict(device) for device in command.devices],
            },
        )
        if command.collector_key != DISCOVERY_COLLECTOR_KEY:  # a discovery snapshot never alerts
            notify_expected_disconnects(
                computing_id=command.computing_id, equipment_ids=detached_equipment, observed_at=command.collected_at
            )
        return _ack(batch)


def _apply_projection(command: DeviceObservationInput, *, received_at) -> set[int]:
    """Write the projection; return equipment ids that went from connected to disconnected."""
    connections = DeviceConnection.objects.filter(
        computing_id=command.computing_id, collector_key=command.collector_key
    )
    input_keys = [device.observation_key for device in command.devices]
    retained_connected = (
        0
        if command.is_complete
        else connections.filter(state=DeviceConnectionState.CONNECTED).exclude(observation_key__in=input_keys).count()
    )
    if retained_connected + sum(device.state == "connected" for device in command.devices) > MAX_DEVICES_PER_COLLECTOR:
        raise ValidationFailed("At most 200 connected devices per collector are supported; send a complete snapshot.")
    present = {row.observation_key: row for row in connections.filter(observation_key__in=input_keys)}
    # Detach notifications can arrive after OS identity metadata disappears.
    # Keep prior evidence for that stable instance; reconnects never inherit it.
    effective_devices = tuple(
        replace(
            device,
            hardware_ids=tuple(
                (item["kind"], item["value"]) for item in present[device.observation_key].hardware_ids or []
            ),
            name=device.name or present[device.observation_key].name,
        )
        if device.state == "disconnected" and not device.hardware_ids and device.observation_key in present
        else device
        for device in command.devices
    )
    matches = match_hardware_ids(
        computing_id=command.computing_id,
        evidence=[(device.hardware_ids, device.interface_name) for device in effective_devices],
    )
    create, update = [], []
    detached_equipment: set[int] = set()
    for device in effective_devices:
        match = matches[(device.hardware_ids, device.interface_name)]
        row = present.get(device.observation_key)
        if row is None:
            row = DeviceConnection(
                computing_id=command.computing_id,
                collector_key=command.collector_key,
                observation_key=device.observation_key,
                first_seen_at=received_at,
            )
            create.append(row)
        else:
            update.append(row)
            detaches = (
                row.state == DeviceConnectionState.CONNECTED and device.state == DeviceConnectionState.DISCONNECTED
            )
            if detaches and row.equipment_id:
                detached_equipment.add(row.equipment_id)
        row.equipment_id, row.interface_id, row.match_status = match.equipment_id, match.interface_id, match.status
        row.generation_key, row.sequence = command.generation_key, command.sequence
        row.name, row.serial_number, row.interface_name = device.name, device.serial_number, device.interface_name
        row.hardware_ids = [{"kind": kind, "value": value} for kind, value in device.hardware_ids]
        row.state, row.observed_at, row.received_at = device.state, command.collected_at, received_at
    DeviceConnection.objects.bulk_create(create, batch_size=MAX_DEVICES_PER_COLLECTOR)
    DeviceConnection.objects.bulk_update(update, _PROJECTION_FIELDS, batch_size=MAX_DEVICES_PER_COLLECTOR)
    if command.is_complete:
        # SQL-bounded reconciliation; omitted records are confirmed absent by
        # this scoped full snapshot. Their identities remain historical.
        omitted = connections.filter(state=DeviceConnectionState.CONNECTED).exclude(observation_key__in=input_keys)
        detached_equipment.update(omitted.filter(equipment_id__isnull=False).values_list("equipment_id", flat=True))
        omitted.update(
            state=DeviceConnectionState.DISCONNECTED,
            generation_key=command.generation_key,
            sequence=command.sequence,
            observed_at=command.collected_at,
            received_at=received_at,
        )
    return detached_equipment


@dataclass(frozen=True, slots=True)
class InvalidateDeviceConnectionsInput:
    computing_id: int


def invalidate_device_connections(command: InvalidateDeviceConnectionsInput, *, actor: ActorContext) -> None:
    """Lifecycle holds identity lock; invalidation never acquires an equipment lock."""
    if command.computing_id not in actor.equipment_ids or "monitoring:invalidate" not in actor.capabilities:
        raise Forbidden("The principal cannot invalidate this computing equipment.")
    with transaction.atomic():
        DeviceObservationCursor.objects.filter(computing_id=command.computing_id).update(is_current=False)
