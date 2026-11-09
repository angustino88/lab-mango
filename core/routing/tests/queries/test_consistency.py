"""Consistent-snapshot reads and digest cache keys for the routing sync selectors."""

import uuid

import pytest
from django.db import connection

from core.routing.application import rotate_sync_epoch
from core.routing.models import RoutingEntity, SyncState
from core.routing.queries.selectors import (
    ChangesReset,
    consistent_read,
    get_stream_changes,
    get_stream_digest,
)

DATA_HASH = "43f154ed4a9512251f4b2bf1e0588c167a2ac83c224de4f4bcc28adf2d720fd5"
AGENT_KEY = "bbbbbbbb-1111-4000-8000-000000000001"


@pytest.mark.django_db(transaction=True)
def test_consistent_read_uses_read_only_repeatable_read_snapshot():
    with consistent_read():
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation = cursor.fetchone()[0]
            cursor.execute("SHOW transaction_read_only")
            read_only = cursor.fetchone()[0]
    assert isolation == "repeatable read"
    assert read_only == "on"


@pytest.mark.django_db(transaction=True)
def test_digest_snapshot_ignores_rows_committed_after_head_was_read():
    SyncState.objects.create(entity_type="agents", version=1, epoch=uuid.uuid4())
    RoutingEntity.objects.create(
        entity_type="agents", key=AGENT_KEY, version=1, state="active", data={}, data_hash=DATA_HASH
    )
    from django.db import connections

    other = connections.create_connection("default")
    try:
        with consistent_read():
            assert SyncState.objects.get(entity_type="agents").version == 1
            # Another session commits a newer row after our snapshot was taken.
            with other.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO labs_routingentity (entity_type, key, version, state, data, data_hash) "
                    "VALUES ('agents', %s, 2, 'active', '{}'::jsonb, %s)",
                    ["bbbbbbbb-1111-4000-8000-000000000002", DATA_HASH],
                )
                cursor.execute("UPDATE labs_syncstate SET version = 2 WHERE entity_type = 'agents'")
            assert RoutingEntity.objects.filter(entity_type="agents", deleted_at__isnull=True).count() == 1
    finally:
        other.close()
    count, _checksum, version, _epoch = get_stream_digest("agents")
    assert (count, version) == (2, 2)


@pytest.mark.django_db
def test_digest_reports_new_epoch_after_rotation_at_same_version():
    SyncState.objects.create(entity_type="agents", version=1, epoch=uuid.uuid4())
    RoutingEntity.objects.create(
        entity_type="agents", key=AGENT_KEY, version=1, state="active", data={}, data_hash=DATA_HASH
    )
    _count, first_checksum, first_version, first_epoch = get_stream_digest("agents")

    new_epoch = rotate_sync_epoch("agents")["agents"]

    _count, checksum, version, epoch = get_stream_digest("agents")
    assert version == first_version == 1
    assert checksum == first_checksum
    assert epoch == new_epoch != first_epoch


@pytest.mark.django_db
def test_changes_reset_when_no_history_is_retained_behind_head():
    epoch = uuid.uuid4()
    SyncState.objects.create(entity_type="agents", version=3, epoch=epoch)

    result = get_stream_changes("agents", since=1, requested_epoch=epoch)

    assert isinstance(result, ChangesReset)
    assert result.reason == "history_pruned"
    assert result.head_version == 3
