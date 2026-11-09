import uuid

import pytest
from django.contrib.auth import get_user_model

from core.agents.models import AgentIdentity
from core.labs.models import (
    ComputingEquipment,
    EquipmentCategory,
    EquipmentKind,
)
from core.routing.application.publish import (
    rebuild_routing_projection,
    rotate_sync_epoch,
)
from core.routing.models import (
    RoutingChange,
    RoutingEntity,
    SyncState,
)
from core.users.models import EntraIdentity


@pytest.fixture
def routing_agent_setup(db):
    actor = get_user_model().objects.create_user(username=f"routing-agent-{uuid.uuid4()}")
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing",
        defaults={"name": "Computing", "definition": "Computing", "active": True},
    )
    kind = EquipmentKind.objects.create(category=category, name=f"Computer-{uuid.uuid4()}")
    equipment = ComputingEquipment.objects.create(sku=f"AGENT-{uuid.uuid4()}", kind=kind, name="Agent host")
    return actor, equipment


@pytest.mark.django_db
def test_rotate_sync_epoch():
    old_epoch = uuid.UUID("11111111-1111-4111-8111-111111111111")
    state = SyncState.objects.create(entity_type="users", version=5, epoch=old_epoch)

    res = rotate_sync_epoch("users")
    assert "users" in res
    assert res["users"] != old_epoch

    state.refresh_from_db()
    assert state.epoch == res["users"]
    assert state.version == 5  # Version preserved


@pytest.mark.django_db
def test_rebuild_routing_projection(routing_agent_setup):
    actor, equipment = routing_agent_setup
    User = get_user_model()
    user = User.objects.create(username="test_user", is_active=True)
    EntraIdentity.objects.create(
        user=user,
        tenant_id="11111111-2222-3333-4444-555555555555",
        object_id="aaaaaaaa-0000-0000-0000-000000000001",
    )
    user_key = "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001"

    agent_uid = uuid.UUID("bbbbbbbb-1111-4000-8000-000000000001")
    AgentIdentity.objects.create(
        equipment=equipment,
        creator=actor,
        agent_uid=agent_uid,
        state=AgentIdentity.State.ACTIVE,
        public_key="a" * 64,
        public_key_sha256="b" * 64,
    )
    agent_key = str(agent_uid)

    # Stale entity in projection to test delete
    stale_key = "entra:11111111-2222-3333-4444-555555555555:cccccccc-0000-0000-0000-000000000001"
    RoutingEntity.objects.create(
        entity_type="users",
        key=stale_key,
        version=1,
        state="active",
        data={},
        data_hash="43f154ed4a9512251f4b2bf1e0588c167a2ac83c224de4f4bcc28adf2d720fd5",
    )
    SyncState.objects.create(entity_type="users", version=1)

    # 1. Verify mode
    verify_res = rebuild_routing_projection(verify=True)
    assert verify_res["users"]["matches"] is False
    assert user_key in verify_res["users"]["to_upsert"]
    assert stale_key in verify_res["users"]["to_delete"]
    assert verify_res["agents"]["matches"] is False
    assert agent_key in verify_res["agents"]["to_upsert"]

    # 2. Execution mode
    rebuild_res = rebuild_routing_projection(verify=False)
    assert rebuild_res["users"]["rebuilt"] is True
    assert rebuild_res["users"]["upserted"] == 1
    assert rebuild_res["users"]["deleted"] == 1
    assert rebuild_res["agents"]["rebuilt"] is True
    assert rebuild_res["agents"]["upserted"] == 1

    # Projection checks
    assert RoutingEntity.objects.filter(entity_type="users", key=user_key, deleted_at__isnull=True).exists()
    assert RoutingEntity.objects.filter(entity_type="users", key=stale_key, deleted_at__isnull=False).exists()
    assert RoutingEntity.objects.filter(entity_type="agents", key=agent_key, deleted_at__isnull=True).exists()

    # Changes checks
    assert RoutingChange.objects.filter(entity_type="users", key=user_key, op="upsert").exists()
    assert RoutingChange.objects.filter(entity_type="users", key=stale_key, op="delete").exists()
    assert RoutingChange.objects.filter(entity_type="agents", key=agent_key, op="upsert").exists()

    # 3. Subsequent verify: clean match
    verify_clean = rebuild_routing_projection(verify=True)
    assert verify_clean["users"]["matches"] is True
    assert verify_clean["agents"]["matches"] is True
