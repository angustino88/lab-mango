"""Read-only selectors, winner pagination, and digest computation for routing sync."""

from __future__ import annotations

import hashlib
import struct
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import Max, Subquery
from django.utils import timezone

from core.routing.models import RoutingChange, RoutingEntity, SyncState

_P = ParamSpec("_P")
_R = TypeVar("_R")


@contextmanager
def consistent_read() -> Iterator[None]:
    """Run reads in one read-only REPEATABLE READ snapshot (SNAP-1, DIG-2, GET-2).

    Under PostgreSQL's default READ COMMITTED each statement sees its own snapshot, so a head
    version and the rows read afterwards could come from different moments. When the caller already
    holds a transaction (tests, composed commands) the isolation level cannot be changed any more;
    the reads then share the caller's transaction as before.
    """
    if connection.in_atomic_block:
        yield
        return
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield


def _consistent(func: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with consistent_read():
            return func(*args, **kwargs)

    return wrapper


@dataclass(frozen=True, slots=True)
class ChangesDelta:
    mode: str  # "delta"
    version: int
    head_version: int
    has_more: bool
    oldest_retained_version: int
    changes: list[dict[str, Any]]
    epoch: uuid.UUID


@dataclass(frozen=True, slots=True)
class ChangesReset:
    mode: str  # "reset"
    reason: str  # "epoch_changed" | "cursor_ahead" | "history_pruned"
    head_version: int
    epoch: uuid.UUID


def compute_digest(rows: Iterable[tuple[str, str, str]]) -> str:
    """Compute digest checksum according to DIG-1.

    Hex SHA-256 over live claims in ascending bytewise key order:
    u32be(len(key)) + key + u32be(len(state)) + state + data_hash (64 ascii chars).
    Lengths are UTF-8 byte counts. An empty stream hashes the empty byte input.
    """
    hasher = hashlib.sha256()
    sorted_rows = sorted(rows, key=lambda row: row[0].encode("utf-8"))
    for key, state, data_hash_hex in sorted_rows:
        key_bytes = key.encode("utf-8")
        state_bytes = state.encode("utf-8")
        hash_bytes = data_hash_hex.encode("ascii")
        hasher.update(
            struct.pack(">I", len(key_bytes))
            + key_bytes
            + struct.pack(">I", len(state_bytes))
            + state_bytes
            + hash_bytes
        )
    return f"sha256:{hasher.hexdigest()}"


def _digest_cache_key(entity_type: str, epoch: uuid.UUID, version: int) -> str:
    # The epoch is part of the key: rotation keeps the version but must not serve the old epoch.
    return f"routing:digest:v2:{entity_type}:{epoch}:{version}"


@_consistent
def get_stream_digest(entity_type: str) -> tuple[int, str, int, uuid.UUID]:
    """Return (count, checksum, version, epoch) from a consistent snapshot.

    Results are cached per (entity_type, epoch, version) in accordance with DIG-3.
    """
    sync_state = SyncState.objects.filter(entity_type=entity_type).first()
    if sync_state is None:
        zero_epoch = uuid.UUID("00000000-0000-0000-0000-000000000000")
        return 0, compute_digest(()), 0, zero_epoch

    cache_key = _digest_cache_key(entity_type, sync_state.epoch, sync_state.version)
    cached = cache.get(cache_key)
    if cached is not None:
        count, checksum, version, epoch_str = cached
        return count, checksum, version, uuid.UUID(epoch_str)

    rows = list(
        RoutingEntity.objects.filter(entity_type=entity_type, deleted_at__isnull=True)
        .order_by("key")
        .values_list("key", "state", "data_hash")
    )
    count = len(rows)
    # Ensure state and data_hash are non-null strings
    cleaned_rows = [
        (key, state or "active", data_hash or "")
        for key, state, data_hash in rows
    ]
    checksum = compute_digest(cleaned_rows)
    cache.set(
        cache_key,
        (count, checksum, sync_state.version, str(sync_state.epoch)),
        timeout=3600,
    )
    return count, checksum, sync_state.version, sync_state.epoch


def get_stream_info(
    backend_id: str,
    enabled_entities: Sequence[str],
    limits: dict[str, int],
) -> dict[str, Any]:
    """Return stream advertisement metadata for GET /internal/info."""
    entities: dict[str, dict[str, Any]] = {}
    for entity in enabled_entities:
        state = SyncState.objects.filter(entity_type=entity).first()
        if state is not None:
            entities[entity] = {
                "version": state.version,
                "epoch": str(state.epoch),
            }
        else:
            entities[entity] = {
                "version": 0,
                "epoch": "00000000-0000-0000-0000-000000000000",
            }

    return {
        "backend_id": backend_id,
        "server_time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entities": entities,
        "limits": limits,
    }


@_consistent
def get_stream_snapshot(
    entity_type: str,
    *,
    after: str | None = None,
    limit: int = 1000,
) -> tuple[int, uuid.UUID, list[dict[str, Any]], str | None]:
    """Read one snapshot page of live claims for a stream.

    Returns (head_version, epoch, items, next_after).
    """
    sync_state = SyncState.objects.filter(entity_type=entity_type).first()
    if sync_state is None:
        zero_epoch = uuid.UUID("00000000-0000-0000-0000-000000000000")
        return 0, zero_epoch, [], None

    qs = RoutingEntity.objects.filter(entity_type=entity_type, deleted_at__isnull=True)
    if after is not None:
        qs = qs.filter(key__gt=after)

    results = list(
        qs.order_by("key").only("key", "version", "state", "data")[: limit + 1]
    )
    has_more = len(results) > limit
    page_rows = results[:limit]

    items = [
        {
            "key": entity.key,
            "version": entity.version,
            "state": entity.state or "active",
            "data": entity.data if entity.data is not None else {},
        }
        for entity in page_rows
    ]
    next_after = page_rows[-1].key if has_more and page_rows else None
    return sync_state.version, sync_state.epoch, items, next_after


@_consistent
def get_stream_changes(
    entity_type: str,
    *,
    since: int,
    requested_epoch: uuid.UUID,
    limit: int = 500,
) -> ChangesDelta | ChangesReset:
    """Read compact change delta or reset for GET /internal/changes/{entity}."""
    sync_state = SyncState.objects.filter(entity_type=entity_type).first()
    if sync_state is None:
        zero_epoch = uuid.UUID("00000000-0000-0000-0000-000000000000")
        if requested_epoch != zero_epoch:
            return ChangesReset(
                mode="reset",
                reason="epoch_changed",
                head_version=0,
                epoch=zero_epoch,
            )
        return ChangesDelta(
            mode="delta",
            version=since,
            head_version=0,
            has_more=False,
            oldest_retained_version=0,
            changes=[],
            epoch=zero_epoch,
        )

    if sync_state.epoch != requested_epoch:
        return ChangesReset(
            mode="reset",
            reason="epoch_changed",
            head_version=sync_state.version,
            epoch=sync_state.epoch,
        )

    if since > sync_state.version:
        return ChangesReset(
            mode="reset",
            reason="cursor_ahead",
            head_version=sync_state.version,
            epoch=sync_state.epoch,
        )

    oldest_retained = (
        RoutingChange.objects.filter(entity_type=entity_type)
        .order_by("version")
        .values_list("version", flat=True)
        .first()
    )
    oldest_retained_version = oldest_retained if oldest_retained is not None else sync_state.version

    # With no retained rows at all, any cursor behind the head has lost history too.
    history_lost = oldest_retained is None and since < sync_state.version
    if history_lost or (oldest_retained is not None and oldest_retained > 1 and since < oldest_retained - 1):
        return ChangesReset(
            mode="reset",
            reason="history_pruned",
            head_version=sync_state.version,
            epoch=sync_state.epoch,
        )

    if since == sync_state.version:
        return ChangesDelta(
            mode="delta",
            version=since,
            head_version=sync_state.version,
            has_more=False,
            oldest_retained_version=oldest_retained_version,
            changes=[],
            epoch=sync_state.epoch,
        )

    head_version = sync_state.version
    window_changes = RoutingChange.objects.filter(
        entity_type=entity_type,
        version__gt=since,
        version__lte=head_version,
    )
    latest_per_key = (
        window_changes.values("key")
        .annotate(max_ver=Max("version"))
        .values("max_ver")
    )
    winning_changes = list(
        RoutingChange.objects.filter(
            entity_type=entity_type,
            version__in=Subquery(latest_per_key),
        )
        .order_by("version")[: limit + 1]
    )

    has_more = len(winning_changes) > limit
    page = winning_changes[:limit]

    changes_data: list[dict[str, Any]] = []
    for c in page:
        if c.op == RoutingChange.Operation.DELETE:
            changes_data.append({
                "version": c.version,
                "op": "delete",
                "key": c.key,
            })
        else:
            changes_data.append({
                "version": c.version,
                "op": "upsert",
                "key": c.key,
                "state": c.state or "active",
                "data": c.data if c.data is not None else {},
            })

    return_version = page[-1].version if (has_more and page) else head_version

    return ChangesDelta(
        mode="delta",
        version=return_version,
        head_version=head_version,
        has_more=has_more,
        oldest_retained_version=oldest_retained_version,
        changes=changes_data,
        epoch=sync_state.epoch,
    )
