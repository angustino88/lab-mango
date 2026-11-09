"""Explicit, administratively provisioned Entra account binding. No email-based linking."""

import uuid

from django.conf import settings
from django.db import models


class EntraIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entra_identity")
    tenant_id = models.UUIDField()
    object_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "object_id"], name="users_entra_unique_subject"),
        ]

    def __str__(self) -> str:
        return f"Entra identity for user {self.user_id}"


class EntraLoginChallenge(models.Model):
    """Short-lived browser-bound nonce; only its digest is persisted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nonce_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
