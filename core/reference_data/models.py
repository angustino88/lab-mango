from django.core.exceptions import ValidationError
from django.db import models


class ProtectedReferenceQuerySet(models.QuerySet):
    """Prevent normal bulk deletion of protected baseline rows."""

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Protected reference data cannot be deleted through the ORM.")

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Protected reference data cannot be deleted through the ORM.")


class ProtectedReferenceManager(models.Manager):
    """Manager for models whose rows must not be deleted by application code."""

    use_in_migrations = False

    def get_queryset(self) -> ProtectedReferenceQuerySet:
        return ProtectedReferenceQuerySet(self.model, using=self._db)


class ProtectedReferenceMixin(models.Model):
    """Opt-in deletion protection for ENSURE_PRESENT reference models."""

    objects = ProtectedReferenceManager()

    class Meta:
        abstract = True

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Protected reference data cannot be deleted through the ORM.")

    def hard_delete(self, using: str | None = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        raise ValidationError("Protected reference data cannot be deleted through the ORM.")


class SeededReferenceList(models.Model):
    """Records that a SEED_ONCE declaration has completed on this database."""

    key = models.CharField(max_length=200)
    model_label = models.CharField(max_length=100)
    identity_field = models.CharField(max_length=100)
    seeded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("key",),
                name="reference_seed_list_key_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.model_label}.{self.identity_field}"


class ReferenceImportReceipt(models.Model):
    """Atomic replay receipt; stores reference payloads, never credentials."""

    principal = models.CharField(max_length=100)
    operation = models.CharField(max_length=200)
    key = models.CharField(max_length=128)
    body_hash = models.CharField(max_length=64)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("principal", "operation", "key"), name="reference_import_receipt_uniq"),
        ]


__all__ = ["ProtectedReferenceMixin", "SeededReferenceList", "ReferenceImportReceipt"]
