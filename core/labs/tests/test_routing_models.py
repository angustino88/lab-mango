import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.models import RoutingChange, RoutingEntity, SyncState


@pytest.mark.django_db
def test_sync_state_uses_stream_key_version_and_epoch():
    state = SyncState.objects.create(entity_type="users")

    assert state.version == 0
    assert isinstance(state.epoch, uuid.UUID)
    assert SyncState.objects.get(pk="users").epoch == state.epoch


@pytest.mark.django_db
@pytest.mark.parametrize("entity_type", ["users", "agents", "equipment", "agent_keys"])
def test_sync_state_accepts_active_and_legacy_stream_labels(entity_type):
    state = SyncState.objects.create(entity_type=entity_type)

    assert state.pk == entity_type


@pytest.mark.django_db
@pytest.mark.parametrize("model", [SyncState, RoutingChange, RoutingEntity])
def test_routing_models_reject_unknown_stream_labels(model):
    with pytest.raises(IntegrityError), transaction.atomic():
        if model is SyncState:
            model.objects.create(entity_type="unknown")
        elif model is RoutingChange:
            model.objects.create(
                entity_type="unknown",
                version=1,
                key=str(uuid.uuid4()),
                op=RoutingChange.Operation.DELETE,
            )
        else:
            model.objects.create(
                entity_type="unknown",
                key=str(uuid.uuid4()),
                version=1,
                deleted_at=timezone.now(),
            )


@pytest.mark.django_db
def test_routing_change_rejects_duplicate_stream_version():
    RoutingChange.objects.create(
        entity_type="equipment",
        version=1,
        key=str(uuid.uuid4()),
        op=RoutingChange.Operation.UPSERT,
        state="active",
        data={},
        data_hash="a" * 64,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        RoutingChange.objects.create(
            entity_type="equipment",
            version=1,
            key=str(uuid.uuid4()),
            op=RoutingChange.Operation.DELETE,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("entity_type", ["users", "agents", "equipment", "agent_keys"])
def test_routing_change_accepts_target_and_legacy_stream_labels(entity_type):
    change = RoutingChange.objects.create(
        entity_type=entity_type,
        version=1,
        key=str(uuid.uuid4()),
        op=RoutingChange.Operation.UPSERT,
        state="active",
        data={},
        data_hash="a" * 64,
    )

    assert change.entity_type == entity_type


@pytest.mark.django_db
def test_routing_change_enforces_payload_shape_for_operation():
    with pytest.raises(IntegrityError), transaction.atomic():
        RoutingChange.objects.create(
            entity_type="equipment",
            version=1,
            key=str(uuid.uuid4()),
            op=RoutingChange.Operation.UPSERT,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        RoutingChange.objects.create(
            entity_type="equipment",
            version=2,
            key=str(uuid.uuid4()),
            op=RoutingChange.Operation.DELETE,
            state="active",
        )


@pytest.mark.django_db
@pytest.mark.parametrize("entity_type", ["users", "agents"])
def test_routing_change_accepts_payload_free_tombstone(entity_type):
    change = RoutingChange.objects.create(
        entity_type=entity_type,
        version=1,
        key=str(uuid.uuid4()),
        op=RoutingChange.Operation.DELETE,
    )

    assert change.state is None
    assert change.data is None
    assert change.data_hash is None


@pytest.mark.django_db
def test_routing_entity_rejects_duplicate_stream_key():
    key = str(uuid.uuid4())
    RoutingEntity.objects.create(
        entity_type="equipment",
        key=key,
        version=1,
        state="active",
        data={},
        data_hash="b" * 64,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        RoutingEntity.objects.create(
            entity_type="equipment",
            key=key,
            version=2,
            state="active",
            data={},
            data_hash="c" * 64,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("entity_type", ["users", "agents", "equipment", "agent_keys"])
def test_routing_entity_accepts_target_and_legacy_stream_labels(entity_type):
    entity = RoutingEntity.objects.create(
        entity_type=entity_type,
        key=str(uuid.uuid4()),
        version=1,
        state="active",
        data={},
        data_hash="b" * 64,
    )

    assert entity.entity_type == entity_type


@pytest.mark.django_db
def test_routing_entity_enforces_live_and_tombstone_payload_shape():
    with pytest.raises(IntegrityError), transaction.atomic():
        RoutingEntity.objects.create(
            entity_type="equipment",
            key=str(uuid.uuid4()),
            version=1,
        )

    tombstone = RoutingEntity.objects.create(
        entity_type="equipment",
        key=str(uuid.uuid4()),
        version=1,
        deleted_at=timezone.now(),
    )
    assert tombstone.pk is not None


