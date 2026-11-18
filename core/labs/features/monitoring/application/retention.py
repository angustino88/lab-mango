"""Bounded purge of device-observation history that no longer serves a purpose.

Batch receipts exist for idempotent replay and sequence-conflict detection. Agents retry
for minutes or hours, never weeks, so receipts older than the receipt window are deleted.
After that, a late duplicate is either stale (sequence at or behind the cursor) or needs a
complete snapshot; it can never rewind current state.

Disconnected projections whose last observation is older than the detached window are
deleted. Connected rows are never purged: they are current state, even when stale.
``inventory_snapshot`` monitoring events follow the monitoring event history policy and
are not touched here.

Race guard: deletes are idempotent and touch only rows past the cutoff. A concurrent
report can only move a row's ``received_at`` forward, which removes it from the
candidate set. Each chunk is its own short transaction, so no long locks are held.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.labs.models.monitoring import DeviceConnection, DeviceConnectionState, DeviceObservationBatch

PURGE_CHUNK_SIZE = 5000


@dataclass(frozen=True, slots=True)
class DeviceObservationPurgeResult:
    batches_deleted: int
    connections_deleted: int


def _purge(queryset, *, limit: int) -> int:
    deleted = 0
    while deleted < limit:
        with transaction.atomic():
            chunk = list(
                queryset.order_by("pk").values_list("pk", flat=True)[: min(PURGE_CHUNK_SIZE, limit - deleted)]
            )
            if not chunk:
                break
            count, _ = queryset.model.objects.filter(pk__in=chunk).delete()
        deleted += count
    return deleted


def purge_device_observation_history(
    *, now: datetime | None = None, max_rows: int = 200_000
) -> DeviceObservationPurgeResult:
    """Delete expired receipts and detached projections, at most ``max_rows`` of each per run."""
    now = now or timezone.now()
    receipt_cutoff = now - timedelta(days=settings.DEVICE_OBSERVATION_RECEIPT_RETENTION_DAYS)
    detached_cutoff = now - timedelta(days=settings.DEVICE_CONNECTION_DETACHED_RETENTION_DAYS)
    return DeviceObservationPurgeResult(
        batches_deleted=_purge(DeviceObservationBatch.objects.filter(received_at__lt=receipt_cutoff), limit=max_rows),
        connections_deleted=_purge(
            DeviceConnection.objects.filter(state=DeviceConnectionState.DISCONNECTED, received_at__lt=detached_cutoff),
            limit=max_rows,
        ),
    )


__all__ = ("DeviceObservationPurgeResult", "purge_device_observation_history")
