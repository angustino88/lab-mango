"""Device-generated public-key identity for a computing equipment agent."""

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class AgentIdentity(TimeStampedModel, UserStampedModel):
    """An enrolled agent; its private key is generated and retained by the device."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        DECOMMISSIONED = "decommissioned", "Decommissioned"

    class KeyAlgorithm(models.TextChoices):
        ED25519 = "Ed25519", "Ed25519"

    class KeyStorage(models.TextChoices):
        TPM = "tpm", "TPM"
        OS_KEYSTORE = "os_keystore", "OS keystore"
        SOFTWARE = "software", "Software key store"

    agent_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    equipment = models.ForeignKey(
        "labs.ComputingEquipment",
        related_name="agent_identities",
        on_delete=models.PROTECT,
    )
    public_key = models.TextField(blank=True, default="")
    public_key_sha256 = models.CharField(max_length=64, blank=True, default="")
    key_algorithm = models.CharField(max_length=8, choices=KeyAlgorithm.choices, blank=True, default="")
    key_storage = models.CharField(max_length=16, choices=KeyStorage.choices, blank=True, default="")
    fingerprint = models.CharField(max_length=128, blank=True, default="")
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    agent_version = models.CharField(max_length=64, blank=True, default="")
    last_seen_at = models.DateTimeField(null=True, blank=True)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    key_rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "labs_agentidentity"
        constraints = [
            models.UniqueConstraint(
                fields=("equipment",),
                condition=Q(state__in=("active", "pending")),
                name="agent_one_live_per_equipment",
            ),
            models.CheckConstraint(
                condition=(~Q(state="active") | (Q(public_key__gt="") & Q(public_key_sha256__gt=""))),
                name="active_agent_has_public_key",
            ),
            models.CheckConstraint(
                condition=Q(key_algorithm="") | Q(key_algorithm="Ed25519"),
                name="agent_key_algorithm_ed25519",
            ),
            models.UniqueConstraint(
                fields=("public_key_sha256",),
                condition=~Q(public_key_sha256=""),
                name="agent_public_key_sha256_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("state", "last_seen_at"), name="agent_state_seen_idx"),
        ]

    def activate(self, *, public_key: str, public_key_sha256: str, key_storage: str, agent_version: str) -> None:
        self.public_key = public_key
        self.public_key_sha256 = public_key_sha256
        self.key_algorithm = self.KeyAlgorithm.ED25519
        self.key_storage = key_storage
        self.agent_version = agent_version
        self.state = self.State.ACTIVE
        self.enrolled_at = timezone.now()


class EnrollmentGrant(TimeStampedModel, UserStampedModel):
    """One-time, equipment-bound bootstrap grant; raw grant is never persisted."""

    agent = models.ForeignKey(
        AgentIdentity,
        related_name="enrollment_grants",
        on_delete=models.PROTECT,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "labs_enrollmentgrant"
        constraints = [
            models.CheckConstraint(
                condition=(Q(used_at__isnull=True) | Q(revoked_at__isnull=True)),
                name="agent_grant_not_used_and_revoked",
            ),
        ]
        indexes = [models.Index(fields=("expires_at", "used_at"), name="agent_grant_expiry_idx")]

    @property
    def is_usable(self) -> bool:
        now = timezone.now()
        return self.used_at is None and self.revoked_at is None and self.expires_at > now
