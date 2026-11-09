"""Agent enrollment provisioning and proof-of-possession commands."""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.agents.contracts import CreateEnrollmentGrantInput, EnrollmentGrantIssued
from core.agents.exceptions import (
    AgentEnrollmentConflict,
    AgentProofInvalid,
    EnrollmentGrantInvalid,
)
from core.agents.models import AgentIdentity, EnrollmentGrant
from core.labs.models import ComputingEquipment
from core.routing.public import publish_agent_identity

GRANT_PREFIX = "eg_"
ENROLLMENT_CONTEXT = b"labmango-enroll-v1"


@transaction.atomic
def require_active_agent_identity(agent_uid: UUID, *, actor: Any = None) -> AgentIdentity:
    """Resolve and lock the active identity named by an agent credential.

    ``actor`` is accepted for a consistent application boundary; identity selection depends only
    on the credential UID and persisted active state.
    """
    try:
        return AgentIdentity.objects.select_for_update().get(agent_uid=agent_uid, state=AgentIdentity.State.ACTIVE)
    except AgentIdentity.DoesNotExist as error:
        raise AgentEnrollmentConflict("Agent identity is not active.") from error


def _urlsafe_b64decode(value: str) -> bytes:
    if not value or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=" for char in value
    ):
        raise ValueError("Invalid base64url value.")
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _public_key(raw: str) -> tuple[Ed25519PublicKey, bytes]:
    """Parse a base64url DER SubjectPublicKeyInfo Ed25519 public key."""
    der = _urlsafe_b64decode(raw)
    key = serialization.load_der_public_key(der)
    if not isinstance(key, Ed25519PublicKey):
        raise AgentProofInvalid("Only Ed25519 enrollment keys are accepted.")
    return key, der


def _grant_digest(grant: str) -> str:
    return hashlib.sha256(grant.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EnrollAgentInput:
    grant: str
    public_key: str
    key_storage: str
    fingerprint: str
    agent_version: str
    proof: str


@transaction.atomic
def create_enrollment_grant(
    command: CreateEnrollmentGrantInput,
    *,
    actor: Any,
) -> EnrollmentGrantIssued:
    """Create pending agent identity and return a one-time grant exactly once."""
    if command.ttl_minutes < 1 or command.ttl_minutes > 60:
        raise ValueError("Enrollment grant TTL must be between 1 and 60 minutes.")

    equipment = ComputingEquipment.objects.select_for_update().get(uid=command.equipment_uid, deleted_at__isnull=True)
    # Expired bootstrap identities are never valid credentials and should not strand re-enrollment.
    now = timezone.now()
    AgentIdentity.objects.filter(
        equipment=equipment,
        state=AgentIdentity.State.PENDING,
        enrollment_grants__used_at__isnull=True,
        enrollment_grants__revoked_at__isnull=True,
        enrollment_grants__expires_at__lte=now,
    ).update(state=AgentIdentity.State.REVOKED, modified=now)
    if AgentIdentity.objects.filter(equipment=equipment, state=AgentIdentity.State.ACTIVE).exists():
        raise AgentEnrollmentConflict("Equipment already has an active agent.")
    if AgentIdentity.objects.filter(equipment=equipment, state=AgentIdentity.State.PENDING).exists():
        raise AgentEnrollmentConflict("Equipment already has a pending agent enrollment.")

    try:
        identity = AgentIdentity(equipment=equipment)
        identity.save(actor=actor)
    except IntegrityError as error:
        raise AgentEnrollmentConflict("Equipment already has a pending or active agent.") from error
    clear_grant = GRANT_PREFIX + secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(minutes=command.ttl_minutes)
    EnrollmentGrant(
        agent=identity,
        token_hash=_grant_digest(clear_grant),
        expires_at=expires_at,
    ).save(actor=actor)
    return EnrollmentGrantIssued(
        agent_uid=identity.agent_uid,
        equipment_uid=equipment.uid,
        grant=clear_grant,
        expires_at=expires_at,
    )


@transaction.atomic
def issue_grant_for_agent(agent_id: int, ttl_minutes: int, *, actor: Any) -> EnrollmentGrantIssued:
    """Issue a new or recovery enrollment grant for an existing agent, revoking prior unredeemed grants."""
    if ttl_minutes < 1 or ttl_minutes > 60:
        raise ValueError("Enrollment grant TTL must be between 1 and 60 minutes.")

    agent = AgentIdentity.objects.select_for_update().get(pk=agent_id)
    if agent.state in (AgentIdentity.State.REVOKED, AgentIdentity.State.DECOMMISSIONED):
        raise AgentEnrollmentConflict("Cannot issue enrollment grant for revoked or decommissioned agent.")

    now = timezone.now()
    EnrollmentGrant.objects.filter(agent=agent, used_at__isnull=True, revoked_at__isnull=True).update(
        revoked_at=now,
        modified=now,
    )
    if agent.state != AgentIdentity.State.PENDING:
        agent.state = AgentIdentity.State.PENDING
        agent.save(actor=actor, update_fields=("state", "modified"))

    clear_grant = GRANT_PREFIX + secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=ttl_minutes)
    EnrollmentGrant(
        agent=agent,
        token_hash=_grant_digest(clear_grant),
        expires_at=expires_at,
    ).save(actor=actor)
    return EnrollmentGrantIssued(
        agent_uid=agent.agent_uid,
        equipment_uid=agent.equipment.uid,
        grant=clear_grant,
        expires_at=expires_at,
    )


@transaction.atomic
def revoke_enrollment_grant(grant_id: int, *, actor: Any) -> None:
    """Revoke an unused grant; an already redeemed grant is immutable."""
    grant = EnrollmentGrant.objects.select_for_update().filter(pk=grant_id).first()
    if grant is None:
        raise EnrollmentGrantInvalid("Enrollment grant is invalid.")
    if grant.used_at is not None:
        raise EnrollmentGrantInvalid("A redeemed enrollment grant cannot be revoked.")
    if grant.revoked_at is None:
        grant.revoked_at = timezone.now()
        grant.save(actor=actor, update_fields=("revoked_at", "modified"))
        if not EnrollmentGrant.objects.filter(
            agent=grant.agent,
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).exists():
            identity = AgentIdentity.objects.select_for_update().get(pk=grant.agent_id)
            if identity.state == AgentIdentity.State.PENDING:
                identity.state = AgentIdentity.State.REVOKED
                identity.save(actor=actor, update_fields=("state", "modified"))


@transaction.atomic
def transition_agent_state(agent_uid: UUID, state: str, *, actor: Any) -> AgentIdentity:
    """Revoke or decommission an enrolled identity without deleting its audit record."""
    allowed = {AgentIdentity.State.REVOKED, AgentIdentity.State.DECOMMISSIONED}
    if state not in allowed:
        raise ValueError("Only revoked or decommissioned terminal states are supported.")
    try:
        identity = AgentIdentity.objects.select_for_update().get(agent_uid=agent_uid)
    except AgentIdentity.DoesNotExist as error:
        raise AgentEnrollmentConflict("Agent identity was not found.") from error
    if identity.state in {AgentIdentity.State.REVOKED, AgentIdentity.State.DECOMMISSIONED}:
        return identity
    if identity.state != AgentIdentity.State.ACTIVE:
        raise AgentEnrollmentConflict("Only an active agent can be revoked or decommissioned.")
    identity.state = state
    identity.save(actor=actor, update_fields=("state", "modified"))
    publish_agent_identity(identity)
    now = timezone.now()
    EnrollmentGrant.objects.filter(agent=identity, used_at__isnull=True, revoked_at__isnull=True).update(
        revoked_at=now,
        modified=now,
    )
    return identity


@transaction.atomic
def enroll_agent(command: EnrollAgentInput) -> AgentIdentity:
    """Redeem a one-time grant using a proof signed by the device-held private key."""
    if not command.grant.startswith(GRANT_PREFIX):
        raise EnrollmentGrantInvalid("Enrollment grant is invalid.")
    try:
        grant_record = (
            EnrollmentGrant.objects.select_for_update()
            .select_related("agent__equipment")
            .get(token_hash=_grant_digest(command.grant))
        )
    except EnrollmentGrant.DoesNotExist as error:
        raise EnrollmentGrantInvalid("Enrollment grant is invalid.") from error
    # Global agent write order: equipment (grant creation) -> grant -> identity ->
    # routing SyncState -> projection. Lock the identity explicitly after the
    # grant; select_related() above is only for reading the equipment relation.
    identity = AgentIdentity.objects.select_for_update().get(pk=grant_record.agent_id)
    if identity.state != AgentIdentity.State.PENDING:
        raise EnrollmentGrantInvalid("Enrollment grant is invalid.")
    grant_record.agent = identity
    if not grant_record.is_usable or grant_record.agent.state != AgentIdentity.State.PENDING:
        raise EnrollmentGrantInvalid("Enrollment grant is invalid.")

    try:
        key, der = _public_key(command.public_key)
        proof = _urlsafe_b64decode(command.proof)
        signed_message = b"\0".join(
            (
                ENROLLMENT_CONTEXT,
                settings.BACKEND_ID.encode("ascii"),
                str(grant_record.agent.agent_uid).encode("ascii"),
                _grant_digest(command.grant).encode("ascii"),
                der,
            )
        )
        key.verify(proof, signed_message)
    except (ValueError, TypeError, InvalidSignature, UnicodeEncodeError) as error:
        raise AgentProofInvalid("Enrollment proof is invalid.") from error

    digest = hashlib.sha256(der).hexdigest()
    if AgentIdentity.objects.filter(public_key_sha256=digest).exists():
        raise AgentEnrollmentConflict("This public key is already enrolled.")
    if command.key_storage not in AgentIdentity.KeyStorage.values:
        raise ValueError("Unsupported key storage tier.")
    if len(command.fingerprint) > 128 or len(command.agent_version) > 64:
        raise ValueError("Enrollment metadata exceeds the permitted length.")
    if not command.agent_version.strip():
        raise ValueError("Agent version is required.")

    identity.activate(
        public_key=command.public_key,
        public_key_sha256=digest,
        key_storage=command.key_storage,
        agent_version=command.agent_version,
    )
    identity.fingerprint = command.fingerprint
    try:
        identity.save(
            update_fields=(
                "public_key",
                "public_key_sha256",
                "key_algorithm",
                "key_storage",
                "agent_version",
                "state",
                "enrolled_at",
                "fingerprint",
                "modified",
            )
        )
    except IntegrityError as error:
        cause = error.__cause__ or error
        constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
        if constraint_name == "agent_one_live_per_equipment":
            raise AgentEnrollmentConflict("Equipment already has a pending or active agent.") from error
        if constraint_name == "agent_public_key_sha256_uniq":
            raise AgentEnrollmentConflict("This public key is already enrolled.") from error
        raise
    # Identity is locked by this command before routing takes its stream lock.
    publish_agent_identity(identity)
    grant_record.used_at = timezone.now()
    grant_record.save(update_fields=("used_at", "modified"))
    return identity
