"""Contract tests for the source-only routing publication boundary."""

import ast
import uuid
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from core.labs.models import (
    EquipmentCategory,
    EquipmentKind,
    RoutingChange,
    RoutingEntity,
    SyncState,
)
from core.routing.application.publish import RoutingChangeInput, _apply_change
from core.routing.exceptions import RoutingPublishError
from core.routing.public import publish_agent_identity, publish_user_identity
from tests.factories import create_computing_equipment

ROUTING_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def routing_agent_setup(db):
    actor = get_user_model().objects.create_user(username=f"routing-agent-{uuid.uuid4()}")
    category = EquipmentCategory.objects.create(
        name=f"Computing-{uuid.uuid4()}", key="computing", definition="Computing", active=True
    )
    kind = EquipmentKind.objects.create(category=category, name=f"Computer-{uuid.uuid4()}")
    equipment = create_computing_equipment(sku=f"AGENT-{uuid.uuid4()}", kind=kind, name="Agent host")
    return actor, equipment


def test_public_surface_excludes_raw_writes_and_rebuild():
    source = ast.parse((ROUTING_ROOT / "public.py").read_text(encoding="utf-8"))
    exported = next(
        ast.literal_eval(node.value)
        for node in source.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    assert set(exported) == {
        "PublishResult",
        "RoutingPublishError",
        "publish_agent_identity",
        "publish_user_identity",
    }
    assert not {"publish", "upsert", "delete", "publish_many", "rebuild_projection"} & set(exported)


@pytest.mark.django_db(transaction=True)
def test_user_publisher_requires_transaction_and_canonical_key():
    key = f"entra:{uuid.uuid4()}:{uuid.uuid4()}"
    with pytest.raises(RoutingPublishError, match="active transaction"):
        publish_user_identity(key=key, user_is_active=True)
    with transaction.atomic(), pytest.raises(RoutingPublishError, match="canonical Entra"):
        publish_user_identity(key="entra:not-a-uuid:not-a-uuid", user_is_active=True)


@pytest.mark.django_db(transaction=True)
def test_agent_publication_requires_transaction(routing_agent_setup):
    actor, equipment = routing_agent_setup
    from core.labs.models import AgentIdentity

    identity = AgentIdentity.objects.create(
        equipment=equipment,
        creator=actor,
        state=AgentIdentity.State.ACTIVE,
        public_key="encoded-public-key",
        public_key_sha256="a" * 64,
    )
    with pytest.raises(RoutingPublishError, match="active transaction"):
        publish_agent_identity(identity)


@pytest.mark.django_db(transaction=True)
def test_agent_publication_rejects_unsaved_source_identity(routing_agent_setup):
    actor, equipment = routing_agent_setup
    from core.labs.models import AgentIdentity

    identity = AgentIdentity(equipment=equipment, creator=actor)
    with transaction.atomic(), pytest.raises(RoutingPublishError, match="persisted agent identity"):
        publish_agent_identity(identity)


@pytest.mark.django_db(transaction=True)
def test_agent_identity_derives_live_record_or_tombstone_from_source(routing_agent_setup):
    actor, equipment = routing_agent_setup
    from core.labs.models import AgentIdentity

    identity = AgentIdentity.objects.create(
        equipment=equipment,
        creator=actor,
        state=AgentIdentity.State.ACTIVE,
        public_key="encoded-public-key",
        public_key_sha256="a" * 64,
    )
    with transaction.atomic():
        live = publish_agent_identity(identity)
    with transaction.atomic():
        identity.state = AgentIdentity.State.REVOKED
        identity.save(update_fields=("state",))
        removed = publish_agent_identity(identity)
    with transaction.atomic():
        repeated = publish_agent_identity(identity)

    projection = RoutingEntity.objects.get(entity_type="agents", key=str(identity.agent_uid))
    live_event = RoutingChange.objects.get(entity_type="agents", version=live.version)
    delete_event = RoutingChange.objects.get(entity_type="agents", version=removed.version)
    assert live.changed and removed.changed and not repeated.changed
    assert SyncState.objects.get(pk="agents").version == 2
    assert live_event.op == RoutingChange.Operation.UPSERT
    assert (live_event.state, live_event.data) == ("active", {})
    assert delete_event.op == RoutingChange.Operation.DELETE
    assert (delete_event.state, delete_event.data, delete_event.data_hash) == (None, None, None)
    assert projection.deleted_at is not None
    assert (projection.state, projection.data, projection.data_hash) == (None, None, None)


@pytest.mark.django_db(transaction=True)
def test_agent_publication_rolls_back_stream_history_and_projection(routing_agent_setup, monkeypatch):
    actor, equipment = routing_agent_setup
    from core.labs.models import AgentIdentity

    original_save = RoutingEntity.save

    def fail_projection_save(instance, *args, **kwargs):
        if instance.entity_type == "agents":
            raise RuntimeError("projection write failed")
        return original_save(instance, *args, **kwargs)

    identity = AgentIdentity.objects.create(
        equipment=equipment,
        creator=actor,
        state=AgentIdentity.State.ACTIVE,
        public_key="encoded-public-key",
        public_key_sha256="a" * 64,
    )
    with transaction.atomic():
        publish_agent_identity(identity)

    with pytest.raises(RuntimeError, match="projection write failed"):
        with transaction.atomic():
            monkeypatch.setattr(RoutingEntity, "save", fail_projection_save)
            state_row = SyncState.objects.select_for_update().get(entity_type="agents")
            projection = RoutingEntity.objects.select_for_update().get(
                entity_type="agents", key=str(identity.agent_uid)
            )
            _apply_change(
                RoutingChangeInput(
                    entity_type="agents",
                    key=str(identity.agent_uid),
                    op=RoutingChange.Operation.DELETE,
                ),
                state_row,
                current=projection,
                payload_hash=None,
            )

    monkeypatch.undo()
    identity.refresh_from_db()
    assert identity.state == AgentIdentity.State.ACTIVE
    assert SyncState.objects.get(pk="agents").version == 1
    assert RoutingChange.objects.filter(entity_type="agents").count() == 1
    assert RoutingEntity.objects.get(entity_type="agents", key=str(identity.agent_uid)).deleted_at is None
