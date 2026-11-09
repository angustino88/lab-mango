import uuid

import pytest
from django.utils import timezone

from core.routing.models import RoutingChange, RoutingEntity, SyncState
from core.routing.queries.selectors import (
    ChangesDelta,
    ChangesReset,
    compute_digest,
    get_stream_changes,
    get_stream_digest,
    get_stream_info,
    get_stream_snapshot,
)

DATA_HASH = "43f154ed4a9512251f4b2bf1e0588c167a2ac83c224de4f4bcc28adf2d720fd5"


def test_compute_digest_appendix_e_vectors():
    """Verify test vectors from Appendix E of backend-routing-sync-spec.md."""
    # Empty
    assert compute_digest([]) == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    # Users stream with two live keys
    users_rows = [
        ("entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001", "active", DATA_HASH),
        ("entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002", "active", DATA_HASH),
    ]
    assert compute_digest(users_rows) == "sha256:e55f21dda5b3742e8baa44eeadfb712312907f2226c940cdb9dc843b5dce5a13"

    # Agents stream with one live key
    agents_rows = [
        ("bbbbbbbb-1111-0000-0000-000000000001", "active", DATA_HASH),
    ]
    assert compute_digest(agents_rows) == "sha256:2ce74e51f5d7cb73601acd527318a602672acf5cb3f712dcf1b18ac183f96e70"


@pytest.mark.django_db
def test_get_stream_info():
    SyncState.objects.create(entity_type="users", version=12, epoch=uuid.UUID("5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10"))
    info = get_stream_info(
        backend_id="dept_a",
        enabled_entities=["users", "agents"],
        limits={"snapshot_max_limit": 5000, "changes_max_limit": 2000, "longpoll_max_wait_s": 30},
    )
    assert info["backend_id"] == "dept_a"
    assert info["entities"]["users"] == {"version": 12, "epoch": "5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10"}
    assert info["entities"]["agents"]["version"] == 0
    assert info["limits"]["snapshot_max_limit"] == 5000


@pytest.mark.django_db
def test_get_stream_snapshot_pagination():
    test_epoch = uuid.UUID("5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10")
    SyncState.objects.create(entity_type="users", version=5, epoch=test_epoch)

    key1 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001"
    key2 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002"
    key3 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000003"
    deleted_key = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000004"

    RoutingEntity.objects.create(entity_type="users", key=key1, version=1, state="active", data={}, data_hash=DATA_HASH)
    RoutingEntity.objects.create(entity_type="users", key=key2, version=2, state="active", data={}, data_hash=DATA_HASH)
    RoutingEntity.objects.create(entity_type="users", key=key3, version=3, state="active", data={}, data_hash=DATA_HASH)
    RoutingEntity.objects.create(
        entity_type="users",
        key=deleted_key,
        version=4,
        state=None,
        data=None,
        data_hash=None,
        deleted_at=timezone.now(),
    )

    # Page 1, limit 2
    head_ver, epoch, items, next_after = get_stream_snapshot("users", limit=2)
    assert head_ver == 5
    assert epoch == test_epoch
    assert len(items) == 2
    assert items[0]["key"] == key1
    assert items[1]["key"] == key2
    assert next_after == key2

    # Page 2, after key2
    head_ver2, epoch2, items2, next_after2 = get_stream_snapshot("users", after=next_after, limit=2)
    assert head_ver2 == 5
    assert epoch2 == test_epoch
    assert len(items2) == 1
    assert items2[0]["key"] == key3
    assert next_after2 is None


@pytest.mark.django_db
def test_get_stream_changes_compaction_and_pagination():
    test_epoch = uuid.UUID("5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10")
    SyncState.objects.create(entity_type="users", version=4, epoch=test_epoch)

    key_a = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001"
    key_b = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002"

    # Version history:
    # v1: key_a upsert
    # v2: key_b upsert
    # v3: key_a delete (winner for key_a is v3)
    # v4: key_b upsert (winner for key_b is v4)
    RoutingChange.objects.create(entity_type="users", version=1, key=key_a, op="upsert", state="active", data={}, data_hash=DATA_HASH)
    RoutingChange.objects.create(entity_type="users", version=2, key=key_b, op="upsert", state="active", data={}, data_hash=DATA_HASH)
    RoutingChange.objects.create(entity_type="users", version=3, key=key_a, op="delete", state=None, data=None, data_hash=None)
    RoutingChange.objects.create(entity_type="users", version=4, key=key_b, op="upsert", state="active", data={}, data_hash=DATA_HASH)

    # Since=0, limit=1 -> first winner is key_a at v3
    delta1 = get_stream_changes("users", since=0, requested_epoch=test_epoch, limit=1)
    assert isinstance(delta1, ChangesDelta)
    assert delta1.mode == "delta"
    assert delta1.has_more is True
    assert delta1.version == 3
    assert len(delta1.changes) == 1
    assert delta1.changes[0] == {"version": 3, "op": "delete", "key": key_a}

    # Next page: since=3, limit=1 -> second winner is key_b at v4
    delta2 = get_stream_changes("users", since=3, requested_epoch=test_epoch, limit=1)
    assert isinstance(delta2, ChangesDelta)
    assert delta2.has_more is False
    assert delta2.version == 4  # advances to head_version
    assert len(delta2.changes) == 1
    assert delta2.changes[0] == {"version": 4, "op": "upsert", "key": key_b, "state": "active", "data": {}}


@pytest.mark.django_db
def test_get_stream_changes_resets():
    real_epoch = uuid.UUID("5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10")
    SyncState.objects.create(entity_type="users", version=10, epoch=real_epoch)
    RoutingChange.objects.create(entity_type="users", version=5, key="k", op="upsert", state="active", data={}, data_hash=DATA_HASH)

    # 1. Epoch mismatch
    wrong_epoch = uuid.UUID("00000000-0000-0000-0000-000000000000")
    res1 = get_stream_changes("users", since=5, requested_epoch=wrong_epoch)
    assert isinstance(res1, ChangesReset)
    assert res1.reason == "epoch_changed"
    assert res1.head_version == 10

    # 2. Cursor ahead
    res2 = get_stream_changes("users", since=15, requested_epoch=real_epoch)
    assert isinstance(res2, ChangesReset)
    assert res2.reason == "cursor_ahead"

    # 3. History pruned (oldest retained is v5, since is 0)
    res3 = get_stream_changes("users", since=0, requested_epoch=real_epoch)
    assert isinstance(res3, ChangesReset)
    assert res3.reason == "history_pruned"


@pytest.mark.django_db
def test_get_stream_digest_calculation_and_caching():
    test_epoch = uuid.UUID("5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10")
    SyncState.objects.create(entity_type="users", version=2, epoch=test_epoch)
    key1 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001"
    key2 = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002"
    RoutingEntity.objects.create(entity_type="users", key=key1, version=1, state="active", data={}, data_hash=DATA_HASH)
    RoutingEntity.objects.create(entity_type="users", key=key2, version=2, state="active", data={}, data_hash=DATA_HASH)

    count, checksum, version, epoch = get_stream_digest("users")
    assert count == 2
    assert checksum == "sha256:e55f21dda5b3742e8baa44eeadfb712312907f2226c940cdb9dc843b5dce5a13"
    assert version == 2
    assert epoch == test_epoch
