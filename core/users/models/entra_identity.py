"""Explicit, administratively provisioned Entra account binding. No email-based linking."""

from django.conf import settings
from django.db import models


class EntraIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entra_identity")
    tenant_id = models.UUIDField()
    object_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Microsoft (Entra) identity"
        verbose_name_plural = "Microsoft (Entra) identities"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "object_id"], name="users_entra_unique_subject"),
        ]

    def __str__(self) -> str:
        return f"Entra identity for user {self.user_id}"


class EntraLoginNonce(models.Model):
    """Nonces already used for an Entra login on this backend; the unique digest makes each one single-use.

    The browser keeps a random secret and sends SHA-256(secret) to Microsoft as the ``nonce``; at login it
    presents the secret. Only the digest of the nonce is stored. Rows can be purged after ``expires_at``,
    because older ID tokens are refused anyway (``ENTRA_LOGIN_MAX_TOKEN_AGE``).
    """

    nonce_digest = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "used login nonce"
        verbose_name_plural = "used login nonces"
