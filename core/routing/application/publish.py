"""Atomic, idempotent writes to the routing change stream and projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from core.routing.exceptions import RoutingPublishError
from core.routing.models import RoutingChange, RoutingEntity, SyncState

if TYPE_CHECKING:
    from core.agents.models import AgentIdentity

logger = logging.getLogger(__name__)

_SUPPORTED_ENTITY_TYPES = frozenset(("users", "agents"))
_USER_KEY_RE = re.compile(
    r"^entra:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

_STREAM_LISTENERS: dict[str, list[asyncio.Event]] = {"users": [], "agents": []}
_THREAD_LISTENERS: dict[str, list[threading.Event]] = {"users": [], "agents": []}


def register_listener(entity_type: str, event: asyncio.Event) -> None:
    """Register an in-memory event to wake up long-poll requests on change."""
    _STREAM_LISTENERS.setdefault(entity_type, []).append(event)


def unregister_listener(entity_type: str, event: asyncio.Event) -> None:
    """Unregister an in-memory event."""
    listeners = _STREAM_LISTENERS.get(entity_type, [])
    if event in listeners:
        listeners.remove(event)


def notify_listeners(entity_type: str) -> None:
    """Wake up all held in-memory long-poll waiters for the given entity."""
    listeners = _STREAM_LISTENERS.get(entity_type, [])
    for event in list(listeners):
        event.set()


def register_thread_listener(entity_type: str, event: threading.Event) -> None:
    """Register a threading event to wake up long-poll requests on change."""
    _THREAD_LISTENERS.setdefault(entity_type, []).append(event)


def unregister_thread_listener(entity_type: str, event: threading.Event) -> None:
    """Unregister a threading event."""
    listeners = _THREAD_LISTENERS.get(entity_type, [])
    if event in listeners:
        listeners.remove(event)


def notify_thread_listeners(entity_type: str) -> None:
    """Wake up all held threading long-poll waiters for the given entity."""
    listeners = _THREAD_LISTENERS.get(entity_type, [])
    for event in list(listeners):
        event.set()


@dataclass(frozen=True, slots=True)
class RoutingChangeInput:
    entity_type: str
    key: str
    op: str
    state: str | None = None
    data: dict | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    version: int
    changed: bool


def publish_agent_identity(identity: AgentIdentity) -> PublishResult:
    """Publish or tombstone a persisted agent identity.

    The caller locks the identity row first; routing then locks SyncState and
    finally the projection row. Agent producers must use the matching order.
    """
    from core.agents.models import AgentIdentity as AgentIdentityModel

    if not connection.in_atomic_block:
        raise RoutingPublishError("Routing publication requires an active transaction.")
    if not identity.pk or identity.state not in AgentIdentityModel.State.values:
        raise RoutingPublishError("A persisted agent identity with a valid state is required.")
    persisted = AgentIdentityModel.objects.filter(pk=identity.pk).values_list("agent_uid", flat=True).first()
    if persisted is None or str(persisted) != str(identity.agent_uid):
        raise RoutingPublishError("A persisted agent identity with a valid state is required.")
    if identity.state == AgentIdentityModel.State.ACTIVE:
        change = _change("agents", _canonical_uuid(identity.agent_uid), RoutingChange.Operation.UPSERT)
    else:
        change = _change("agents", _canonical_uuid(identity.agent_uid), RoutingChange.Operation.DELETE)
    return _publish(change)


def publish_user_identity(*, key: str, user_is_active: bool) -> PublishResult:
    """Publish or tombstone from the persisted Entra identity and user state.

    The users owner derives ``key`` from locked persisted identity values;
    routing deliberately does not import or query the users ORM.
    """
    if not connection.in_atomic_block:
        raise RoutingPublishError("Routing publication requires an active transaction.")
    if not isinstance(user_is_active, bool):
        raise RoutingPublishError("User activity state must be boolean.")
    if not isinstance(key, str) or not _USER_KEY_RE.fullmatch(key):
        raise RoutingPublishError("User routing keys must use the canonical Entra key format.")
    op = RoutingChange.Operation.UPSERT if user_is_active else RoutingChange.Operation.DELETE
    return _publish(_change("users", key, op))


def rotate_sync_epoch(entity_type: str | None = None) -> dict[str, uuid.UUID]:
    """Rotate the epoch for the specified entity stream or all supported streams.

    A changed epoch invalidates the Router cursor and triggers a full snapshot scan.
    """
    targets: Sequence[str] = (entity_type,) if entity_type is not None else ("users", "agents")
    for target in targets:
        if target not in _SUPPORTED_ENTITY_TYPES:
            raise RoutingPublishError(f"Unsupported entity type for epoch rotation: {target}")

    results: dict[str, uuid.UUID] = {}
    with transaction.atomic():
        for target in targets:
            state_row = _lock_stream(target)
            new_epoch = uuid.uuid4()
            state_row.epoch = new_epoch
            state_row.save(update_fields=("epoch",))
            results[target] = new_epoch
            logger.info("Rotated sync epoch for %s to %s", target, new_epoch)
    return results


def rebuild_routing_projection(
    entity_type: str | None = None,
    *,
    verify: bool = False,
) -> dict[str, Any]:
    """Recompute RoutingEntity projection from domain data.

    In verify mode, computes and returns differences without making database mutations.
    In write mode, publishes differences sequentially after head_version.
    """
    targets: Sequence[str] = (entity_type,) if entity_type is not None else ("users", "agents")
    for target in targets:
        if target not in _SUPPORTED_ENTITY_TYPES:
            raise RoutingPublishError(f"Unsupported entity type for projection rebuild: {target}")

    summary: dict[str, Any] = {}
    with transaction.atomic():
        for target in targets:
            target_keys = _collect_domain_keys(target)
            current_live_rows = {
                entity.key: entity
                for entity in RoutingEntity.objects.filter(entity_type=target, deleted_at__isnull=True)
            }
            active_hash = _payload_hash(state="active", data={})

            to_upsert: list[str] = []
            for key in sorted(target_keys):
                existing = current_live_rows.get(key)
                if existing is None or existing.data_hash != active_hash or existing.state != "active":
                    to_upsert.append(key)

            to_delete: list[str] = []
            for key in sorted(current_live_rows):
                if key not in target_keys:
                    to_delete.append(key)

            unchanged_count = len(target_keys) - len(to_upsert)

            if verify:
                summary[target] = {
                    "to_upsert": to_upsert,
                    "to_delete": to_delete,
                    "unchanged": unchanged_count,
                    "matches": len(to_upsert) == 0 and len(to_delete) == 0,
                }
            else:
                _lock_stream(target)
                upsert_count = 0
                delete_count = 0
                for key in to_upsert:
                    _publish(_change(target, key, RoutingChange.Operation.UPSERT))
                    upsert_count += 1
                for key in to_delete:
                    _publish(_change(target, key, RoutingChange.Operation.DELETE))
                    delete_count += 1

                current_head = SyncState.objects.get(entity_type=target).version
                summary[target] = {
                    "rebuilt": True,
                    "upserted": upsert_count,
                    "deleted": delete_count,
                    "unchanged": unchanged_count,
                    "head_version": current_head,
                }
    return summary


def _collect_domain_keys(entity_type: str) -> set[str]:
    """Extract eligible domain keys from source aggregates."""
    if entity_type == "users":
        user_model = get_user_model()
        users = (
            user_model.objects.filter(is_active=True, entra_identity__isnull=False)
            .select_related("entra_identity")
            .only("entra_identity__tenant_id", "entra_identity__object_id")
        )
        return {
            f"entra:{u.entra_identity.tenant_id}:{u.entra_identity.object_id}".lower()
            for u in users
        }
    if entity_type == "agents":
        from core.agents.models import AgentIdentity as AgentIdentityModel

        agents = AgentIdentityModel.objects.filter(state=AgentIdentityModel.State.ACTIVE).values_list("agent_uid", flat=True)
        return {str(uid).lower() for uid in agents}
    return set()


def _change(entity_type: str, key: str, op: str) -> RoutingChangeInput:
    if op == RoutingChange.Operation.UPSERT:
        return RoutingChangeInput(entity_type=entity_type, key=key, op=op, state="active", data={})
    return RoutingChangeInput(entity_type=entity_type, key=key, op=op)


def _canonical_uuid(value: object) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RoutingPublishError("Routing source identity has an invalid UUID.") from exc
    return str(parsed)


def _publish(change: RoutingChangeInput) -> PublishResult:
    """Private primitive; callers use source-specific commands."""
    if not connection.in_atomic_block:
        raise RoutingPublishError("Routing publication requires an active transaction.")
    _validate(change)
    state_row = _lock_stream(change.entity_type)
    current = RoutingEntity.objects.select_for_update().filter(entity_type=change.entity_type, key=change.key).first()

    if change.op == RoutingChange.Operation.DELETE:
        if current is None or current.deleted_at is not None:
            return PublishResult(version=state_row.version, changed=False)
        return _apply_change(change, state_row, current=current, payload_hash=None)

    payload_hash = _payload_hash(state=change.state, data=change.data)
    if (
        current is not None
        and current.deleted_at is None
        and current.data_hash == payload_hash
        and current.state == change.state
    ):
        return PublishResult(version=state_row.version, changed=False)
    return _apply_change(change, state_row, current=current, payload_hash=payload_hash)


def _validate(change: RoutingChangeInput) -> None:
    if change.entity_type not in _SUPPORTED_ENTITY_TYPES:
        raise RoutingPublishError("Only users and agents routing streams may be written.")
    if not isinstance(change.key, str) or not change.key or len(change.key) > 128:
        raise RoutingPublishError("Routing key must be a non-empty string of at most 128 characters.")
    if change.entity_type == "users" and not _USER_KEY_RE.fullmatch(change.key):
        raise RoutingPublishError("User routing keys must use the canonical Entra key format.")
    if change.entity_type == "agents":
        try:
            parsed = uuid.UUID(change.key)
            if str(parsed) != change.key or parsed.version != 4 or parsed.variant != uuid.RFC_4122:
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise RoutingPublishError("Agent routing keys must be canonical UUID strings.") from exc
    if change.op == RoutingChange.Operation.DELETE:
        if any(value is not None for value in (change.state, change.data)):
            raise RoutingPublishError("Delete changes must not include payload data.")
        return
    if change.op != RoutingChange.Operation.UPSERT:
        raise RoutingPublishError("Routing operation must be upsert or delete.")
    if change.state != "active" or not isinstance(change.data, dict) or change.data:
        raise RoutingPublishError("Routing upserts require state='active' and an empty object payload.")


def _lock_stream(entity_type: str) -> SyncState:
    """Create the stream row conflict-safely, then lock it before projection."""
    SyncState.objects.get_or_create(entity_type=entity_type)
    return SyncState.objects.select_for_update().get(entity_type=entity_type)


def _apply_change(
    change: RoutingChangeInput,
    state_row: SyncState,
    *,
    current: RoutingEntity | None,
    payload_hash: str | None,
) -> PublishResult:
    version = state_row.version + 1
    state = change.state if change.op == RoutingChange.Operation.UPSERT else None
    data = change.data if change.op == RoutingChange.Operation.UPSERT else None
    RoutingChange.objects.create(
        entity_type=change.entity_type,
        version=version,
        key=change.key,
        op=change.op,
        state=state,
        data=data,
        data_hash=payload_hash,
    )
    if current is None:
        current = RoutingEntity(entity_type=change.entity_type, key=change.key)
    current.version = version
    current.state = state
    current.data = data
    current.data_hash = payload_hash
    current.deleted_at = timezone.now() if change.op == RoutingChange.Operation.DELETE else None
    current.save()
    state_row.version = version
    state_row.save(update_fields=("version",))

    # Advisory wake-up for long-poll listeners after commit
    connection.on_commit(lambda: notify_listeners(change.entity_type))
    connection.on_commit(lambda: notify_thread_listeners(change.entity_type))
    connection.on_commit(lambda: _send_pg_notify(change.entity_type))

    return PublishResult(version=version, changed=True)


def _send_pg_notify(entity_type: str) -> None:
    if connection.vendor == "postgresql":
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"NOTIFY routing_{entity_type}")
        except Exception:
            logger.warning("Advisory NOTIFY failed for routing_%s", entity_type, exc_info=True)


def _payload_hash(*, state: str | None, data: dict | None) -> str:
    canonical = json.dumps(
        {"data": data, "state": state},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
