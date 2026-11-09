"""Tests for device-generated-key enrollment and one-time grants."""

import base64
import hashlib
import inspect
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.agents.application import (
    ENROLLMENT_CONTEXT,
    EnrollAgentInput,
    create_enrollment_grant,
    enroll_agent,
    revoke_enrollment_grant,
    transition_agent_state,
)
from core.agents.contracts import CreateEnrollmentGrantInput
from core.agents.exceptions import AgentEnrollmentConflict, EnrollmentGrantInvalid
from core.labs.models import (
    AgentIdentity,
    ComputingEquipment,
    EnrollmentGrant,
    EquipmentCategory,
    EquipmentKind,
    RoutingChange,
    RoutingEntity,
    SyncState,
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@pytest.fixture
def agent_setup(db):
    user_model = get_user_model()
    actor = user_model.objects.create_user(username="agent-admin", password="unused")
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    equipment = ComputingEquipment.objects.create(sku="AGENT-01", kind=kind, name="Agent host")
    return actor, equipment


def _enroll_input(grant: str, agent_uid, key_storage="tpm") -> EnrollAgentInput:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    grant_hash = hashlib.sha256(grant.encode()).hexdigest()
    from django.conf import settings

    signed = b"\0".join(
        (
            ENROLLMENT_CONTEXT,
            settings.BACKEND_ID.encode("ascii"),
            str(agent_uid).encode("ascii"),
            grant_hash.encode("ascii"),
            public_der,
        )
    )
    return EnrollAgentInput(
        grant=grant,
        public_key=_b64(public_der),
        key_storage=key_storage,
        fingerprint="sha256:test-device-fingerprint",
        agent_version="1.0.0",
        proof=_b64(private_key.sign(signed)),
    )


def test_create_grant_stores_only_hash_and_returns_pending_server_identity(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )

    identity = AgentIdentity.objects.get(agent_uid=issued.agent_uid)
    grant = EnrollmentGrant.objects.get(agent=identity)
    assert identity.state == AgentIdentity.State.PENDING
    assert identity.equipment_id == equipment.pk
    assert grant.token_hash == hashlib.sha256(issued.grant.encode()).hexdigest()
    assert issued.grant not in grant.token_hash
    assert grant.expires_at > timezone.now()


def test_enroll_activates_only_after_device_proves_private_key_possession(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    command = _enroll_input(issued.grant, issued.agent_uid)

    identity = enroll_agent(command)

    identity.refresh_from_db()
    assert identity.state == AgentIdentity.State.ACTIVE
    assert identity.equipment_id == equipment.pk
    assert identity.public_key
    assert identity.public_key_sha256
    assert EnrollmentGrant.objects.get(agent=identity).used_at is not None
    route = RoutingEntity.objects.get(entity_type="agents", key=str(identity.agent_uid))
    assert route.deleted_at is None
    assert (route.state, route.data) == ("active", {})
    assert SyncState.objects.get(pk="agents").version == 1
    assert list(
        RoutingChange.objects.filter(entity_type="agents", key=str(identity.agent_uid)).values_list("op", flat=True)
    ) == [RoutingChange.Operation.UPSERT]


def test_enroll_rejects_wrong_proof_without_consuming_grant(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    command = _enroll_input(issued.grant, issued.agent_uid)
    invalid = EnrollAgentInput(
        grant=command.grant,
        public_key=command.public_key,
        key_storage=command.key_storage,
        fingerprint=command.fingerprint,
        agent_version=command.agent_version,
        proof=_b64(b"invalid"),
    )

    from core.agents.exceptions import AgentProofInvalid

    with pytest.raises(AgentProofInvalid):
        enroll_agent(invalid)
    assert EnrollmentGrant.objects.get(agent__agent_uid=issued.agent_uid).used_at is None


def test_grant_can_only_be_redeemed_once(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    command = _enroll_input(issued.grant, issued.agent_uid)
    enroll_agent(command)

    with pytest.raises(EnrollmentGrantInvalid):
        enroll_agent(command)


def test_pending_grant_conflicts_when_active_agent_exists(agent_setup):
    actor, equipment = agent_setup
    AgentIdentity.objects.create(
        equipment=equipment,
        creator=actor,
        state=AgentIdentity.State.ACTIVE,
        public_key="encoded-public-key",
        public_key_sha256="a" * 64,
    )

    with pytest.raises(AgentEnrollmentConflict):
        create_enrollment_grant(
            CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
            actor=actor,
        )


def test_enrollment_ttl_is_bounded(agent_setup):
    actor, equipment = agent_setup
    with pytest.raises(ValueError):
        create_enrollment_grant(
            CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=61),
            actor=actor,
        )


@pytest.mark.parametrize("ttl_minutes", [0, -1])
def test_enrollment_ttl_must_be_positive(agent_setup, ttl_minutes):
    actor, equipment = agent_setup

    with pytest.raises(ValueError):
        create_enrollment_grant(
            CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=ttl_minutes),
            actor=actor,
        )

    assert not AgentIdentity.objects.filter(equipment=equipment).exists()
    assert not EnrollmentGrant.objects.filter(agent__equipment=equipment).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key_storage", "cloud"),
        ("fingerprint", "f" * 129),
        ("agent_version", "v" * 65),
        ("agent_version", "   "),
    ],
)
def test_enrollment_rejects_invalid_metadata_without_consuming_grant_or_publishing(agent_setup, field, value):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    valid_command = _enroll_input(issued.grant, issued.agent_uid)
    metadata = {
        "key_storage": valid_command.key_storage,
        "fingerprint": valid_command.fingerprint,
        "agent_version": valid_command.agent_version,
    }
    metadata[field] = value
    command = EnrollAgentInput(
        grant=valid_command.grant,
        public_key=valid_command.public_key,
        key_storage=metadata["key_storage"],
        fingerprint=metadata["fingerprint"],
        agent_version=metadata["agent_version"],
        proof=valid_command.proof,
    )

    with pytest.raises(ValueError):
        enroll_agent(command)

    identity = AgentIdentity.objects.get(agent_uid=issued.agent_uid)
    grant = EnrollmentGrant.objects.get(agent=identity)
    assert identity.state == AgentIdentity.State.PENDING
    assert identity.public_key == ""
    assert grant.used_at is None
    assert not SyncState.objects.filter(pk="agents").exists()
    assert not RoutingChange.objects.filter(entity_type="agents").exists()
    assert not RoutingEntity.objects.filter(entity_type="agents").exists()


def test_expired_pending_enrollment_does_not_block_reissue(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    EnrollmentGrant.objects.filter(agent__agent_uid=issued.agent_uid).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    replacement = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )

    assert replacement.agent_uid != issued.agent_uid
    assert AgentIdentity.objects.get(agent_uid=issued.agent_uid).state == AgentIdentity.State.REVOKED


def test_revoking_active_agent_preserves_identity_and_revokes_unused_grants(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    active = enroll_agent(_enroll_input(issued.grant, issued.agent_uid))

    revoked = transition_agent_state(active.agent_uid, AgentIdentity.State.REVOKED, actor=actor)

    assert revoked.state == AgentIdentity.State.REVOKED
    assert AgentIdentity.objects.filter(pk=active.pk).exists()
    route = RoutingEntity.objects.get(entity_type="agents", key=str(active.agent_uid))
    assert route.deleted_at is not None
    assert (route.state, route.data, route.data_hash) == (None, None, None)
    assert SyncState.objects.get(pk="agents").version == 2
    assert list(
        RoutingChange.objects.filter(entity_type="agents", key=str(active.agent_uid)).values_list("op", flat=True)
    ) == [RoutingChange.Operation.UPSERT, RoutingChange.Operation.DELETE]
    terminal_event_count = RoutingChange.objects.filter(entity_type="agents", key=str(active.agent_uid)).count()
    transition_agent_state(active.agent_uid, AgentIdentity.State.REVOKED, actor=actor)
    assert (
        RoutingChange.objects.filter(entity_type="agents", key=str(active.agent_uid)).count() == terminal_event_count
    )
    assert EnrollmentGrant.objects.filter(agent=active, used_at__isnull=True, revoked_at__isnull=True).count() == 0
    with pytest.raises(ValueError):
        transition_agent_state(active.agent_uid, AgentIdentity.State.ACTIVE, actor=actor)


@pytest.mark.parametrize("terminal_state", [AgentIdentity.State.REVOKED, AgentIdentity.State.DECOMMISSIONED])
def test_agent_transition_to_terminal_state_is_published_once(agent_setup, terminal_state):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    active = enroll_agent(_enroll_input(issued.grant, issued.agent_uid))

    terminal = transition_agent_state(active.agent_uid, terminal_state, actor=actor)
    repeated = transition_agent_state(active.agent_uid, terminal_state, actor=actor)

    assert terminal.state == repeated.state == terminal_state
    assert SyncState.objects.get(pk="agents").version == 2
    assert list(
        RoutingChange.objects.filter(entity_type="agents", key=str(active.agent_uid)).values_list("op", flat=True)
    ) == [RoutingChange.Operation.UPSERT, RoutingChange.Operation.DELETE]


def test_agent_activation_routing_failure_rolls_back_enrollment(agent_setup, monkeypatch):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    command = _enroll_input(issued.grant, issued.agent_uid)

    def fail_publication(identity):
        raise RuntimeError("routing unavailable")

    monkeypatch.setattr("core.agents.application.publish_agent_identity", fail_publication)
    with pytest.raises(RuntimeError, match="routing unavailable"):
        enroll_agent(command)

    identity = AgentIdentity.objects.get(agent_uid=issued.agent_uid)
    grant = EnrollmentGrant.objects.get(agent=identity)
    assert identity.state == AgentIdentity.State.PENDING
    assert grant.used_at is None
    assert not SyncState.objects.filter(pk="agents").exists()
    assert not RoutingChange.objects.filter(entity_type="agents").exists()
    assert not RoutingEntity.objects.filter(entity_type="agents").exists()


def test_agent_revocation_routing_failure_rolls_back_transition(agent_setup, monkeypatch):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    active = enroll_agent(_enroll_input(issued.grant, issued.agent_uid))

    def fail_publication(identity):
        raise RuntimeError("routing unavailable")

    monkeypatch.setattr("core.agents.application.publish_agent_identity", fail_publication)
    with pytest.raises(RuntimeError, match="routing unavailable"):
        transition_agent_state(active.agent_uid, AgentIdentity.State.REVOKED, actor=actor)

    active.refresh_from_db()
    assert active.state == AgentIdentity.State.ACTIVE
    route = RoutingEntity.objects.get(entity_type="agents", key=str(active.agent_uid))
    assert route.deleted_at is None
    assert SyncState.objects.get(pk="agents").version == 1
    assert RoutingChange.objects.filter(entity_type="agents", key=str(active.agent_uid)).count() == 1


def test_enrollment_locks_source_identity_before_routing_publication():
    source = inspect.getsource(enroll_agent)
    identity_lock = source.index("AgentIdentity.objects.select_for_update().get")
    identity_save = source.index("identity.save(", identity_lock)
    publication = source.index("publish_agent_identity(identity)", identity_save)

    assert identity_lock < identity_save < publication


def test_revoking_unused_grant_also_retires_pending_identity(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    grant = EnrollmentGrant.objects.get(agent__agent_uid=issued.agent_uid)

    revoke_enrollment_grant(grant.pk, actor=actor)

    assert AgentIdentity.objects.get(agent_uid=issued.agent_uid).state == AgentIdentity.State.REVOKED
    assert not EnrollmentGrant.objects.get(pk=grant.pk).is_usable


def test_rejects_malformed_public_key_encoding(agent_setup):
    actor, equipment = agent_setup
    issued = create_enrollment_grant(
        CreateEnrollmentGrantInput(equipment_uid=equipment.uid, ttl_minutes=30),
        actor=actor,
    )
    command = _enroll_input(issued.grant, issued.agent_uid)
    invalid = EnrollAgentInput(
        grant=command.grant,
        public_key="!!!",
        key_storage=command.key_storage,
        fingerprint=command.fingerprint,
        agent_version=command.agent_version,
        proof=command.proof,
    )

    from core.agents.exceptions import AgentProofInvalid

    with pytest.raises(AgentProofInvalid):
        enroll_agent(invalid)


def test_database_rejects_second_live_agent_for_equipment(agent_setup):
    actor, equipment = agent_setup
    AgentIdentity.objects.create(equipment=equipment, creator=actor, state=AgentIdentity.State.PENDING)

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        AgentIdentity.objects.create(equipment=equipment, creator=actor, state=AgentIdentity.State.PENDING)


def test_database_rejects_active_identity_without_public_key(agent_setup):
    actor, equipment = agent_setup
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        AgentIdentity.objects.create(equipment=equipment, creator=actor, state=AgentIdentity.State.ACTIVE)


def test_database_rejects_unknown_algorithm(agent_setup):
    actor, equipment = agent_setup
    identity = AgentIdentity.objects.create(equipment=equipment, creator=actor)
    identity.key_algorithm = "ES256"

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        identity.save(update_fields=("key_algorithm",))
