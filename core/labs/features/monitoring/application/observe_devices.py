"""Atomic, ordered observation ingestion. Caller holds equipment then agent identity.

Race guard: equipment parent lock, cursor lock, plus DB batch/sequence/connection
uniqueness. Lock order: equipment -> authenticated identity -> cursor -> projections.
No network side effects. Replay is content-addressed and never refreshes freshness.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from uuid import uuid5

from django.db import transaction
from django.utils import timezone

from core.common.contracts import ActorContext
from core.common.db.idempotency import try_claim_operation
from core.common.domain.errors import Forbidden, ValidationFailed
from core.labs.features.equipment.public import lock_monitoring_computer, match_observed_devices
from core.labs.features.monitoring.contracts import DeviceObservationInput, ObservationAcknowledgment
from core.labs.features.monitoring.exceptions import ObservationConflict, ObservationInProgress, ObservationKeyReuse
from core.labs.models.monitoring import (
    DeviceConnection,
    DeviceObservationBatch,
    DeviceObservationCursor,
    MonitoringEvent,
)


def _validate(command: DeviceObservationInput) -> None:
    if not 1 <= command.sequence <= 9007199254740991 or len(command.devices) > 200:
        raise ValidationFailed("Sequence or device count exceeds the observation limits.")
    if not timezone.is_aware(command.collected_at) or command.collected_at > timezone.now() + timedelta(minutes=5):
        raise ValidationFailed("Collection time must be timezone-aware and not more than five minutes in the future.")
    keys = [device.observation_key for device in command.devices]
    if len(keys) != len(set(keys)):
        raise ValidationFailed("Observation keys must be unique within a snapshot.")
    for device in command.devices:
        if (
            device.state not in ("connected", "disconnected")
            or not device.observation_key
            or not device.interface_name
        ):
            raise ValidationFailed("Each device needs a key, interface name and valid observed state.")


def _ack(batch: DeviceObservationBatch, *, replayed: bool = False) -> ObservationAcknowledgment:
    return ObservationAcknowledgment(
        batch.batch_key, batch.sequence, "applied" if batch.is_applied else "stale", batch.received_at, replayed
    )


def observe_devices(command: DeviceObservationInput, *, actor: ActorContext) -> ObservationAcknowledgment:
    if command.computer_id not in actor.equipment_ids or "monitoring:report" not in actor.capabilities:
        raise Forbidden("The principal cannot report for this computer.")
    _validate(command)
    content = asdict(command)
    content_hash = hashlib.sha256(
        json.dumps(content, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with transaction.atomic():
        scope = f"POST:/agent/device-observations/actions/report:{command.computer_id}:{command.generation_key}:{command.batch_key}".encode()
        if not try_claim_operation(scope):
            raise ObservationInProgress("This request is still running.")
        # Reentrant when called by the authenticated agent workflow. Also protects
        # internal callers against cursor creation races.
        lock_monitoring_computer(command.computer_id)
        replay = DeviceObservationBatch.objects.filter(
            computer_id=command.computer_id, generation_key=command.generation_key, batch_key=command.batch_key
        ).first()
        if replay:
            if replay.content_hash != content_hash:
                raise ObservationKeyReuse("This idempotency key was already used with different content.")
            return _ack(replay, replayed=True)
        if DeviceObservationBatch.objects.filter(
            computer_id=command.computer_id,
            generation_key=command.generation_key,
            collector_key=command.collector_key,
            sequence=command.sequence,
        ).exists():
            raise ObservationConflict("This sequence was already used by another batch.")
        cursor = (
            DeviceObservationCursor.objects.select_for_update()
            .filter(computer_id=command.computer_id, collector_key=command.collector_key)
            .first()
        )
        needs_snapshot = cursor is None or cursor.generation_key != command.generation_key or not cursor.is_current
        if needs_snapshot and not command.is_complete:
            raise ObservationConflict("A complete snapshot is required for this collector and enrollment generation.")
        is_applied = needs_snapshot or (cursor is not None and command.sequence > cursor.sequence)
        received_at = timezone.now()
        batch = DeviceObservationBatch.objects.create(
            computer_id=command.computer_id,
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
        connections = DeviceConnection.objects.filter(
            computer_id=command.computer_id, collector_key=command.collector_key
        )
        input_keys = [device.observation_key for device in command.devices]
        retained_connected = (
            0
            if command.is_complete
            else connections.filter(state="connected").exclude(observation_key__in=input_keys).count()
        )
        if retained_connected + sum(device.state == "connected" for device in command.devices) > 200:
            raise ValidationFailed(
                "At most 200 connected devices per collector are supported; send a complete snapshot."
            )
        present = {
            row.observation_key: row
            for row in connections.filter(observation_key__in=[device.observation_key for device in command.devices])
        }
        # Detach notifications can arrive after OS identity metadata disappears.
        # Keep prior evidence for that stable instance; reconnects never inherit it.
        effective_devices = tuple(
            replace(
                device,
                serial_number=present[device.observation_key].serial_number,
                name=device.name or present[device.observation_key].name,
            )
            if device.state == "disconnected" and not device.serial_number and device.observation_key in present
            else device
            for device in command.devices
        )
        matches = match_observed_devices(
            tuple((device.serial_number, device.interface_name) for device in effective_devices)
        )
        create, update = [], []
        for device in effective_devices:
            match = matches[(device.serial_number, device.interface_name)]
            row = present.get(device.observation_key)
            if row is None:
                row = DeviceConnection(
                    computer_id=command.computer_id,
                    collector_key=command.collector_key,
                    observation_key=device.observation_key,
                    first_seen_at=received_at,
                )
                create.append(row)
            else:
                update.append(row)
            row.equipment_id, row.interface_id, row.match_status = match.equipment_id, match.interface_id, match.status
            row.generation_key, row.sequence = command.generation_key, command.sequence
            row.name, row.serial_number, row.interface_name = device.name, device.serial_number, device.interface_name
            row.state, row.observed_at, row.received_at = device.state, command.collected_at, received_at
        DeviceConnection.objects.bulk_create(create, batch_size=200)
        DeviceConnection.objects.bulk_update(
            update,
            (
                "equipment",
                "interface",
                "match_status",
                "generation_key",
                "sequence",
                "name",
                "serial_number",
                "interface_name",
                "state",
                "observed_at",
                "received_at",
            ),
            batch_size=200,
        )
        if command.is_complete:
            # SQL-bounded reconciliation; omitted records are confirmed absent by
            # this scoped full snapshot. Their identities remain historical.
            connections.filter(state="connected").exclude(observation_key__in=input_keys).update(
                state="disconnected",
                generation_key=command.generation_key,
                sequence=command.sequence,
                observed_at=command.collected_at,
                received_at=received_at,
            )
        DeviceObservationCursor.objects.update_or_create(
            computer_id=command.computer_id,
            collector_key=command.collector_key,
            defaults={"generation_key": command.generation_key, "sequence": command.sequence, "is_current": True},
        )
        MonitoringEvent.objects.create(
            computer_id=command.computer_id,
            agent_id=command.agent_key,
            event_id=uuid5(command.generation_key, str(command.batch_key)),
            action="inventory_snapshot",
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
        return _ack(batch)


@dataclass(frozen=True, slots=True)
class InvalidateDeviceConnectionsInput:
    computer_id: int


def invalidate_device_connections(command: InvalidateDeviceConnectionsInput, *, actor: ActorContext) -> None:
    """Lifecycle holds identity lock; invalidation never acquires an equipment lock."""
    if command.computer_id not in actor.equipment_ids or "monitoring:invalidate" not in actor.capabilities:
        raise Forbidden("The principal cannot invalidate this computer.")
    with transaction.atomic():
        DeviceObservationCursor.objects.filter(computer_id=command.computer_id).update(is_current=False)
