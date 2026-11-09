"""Timestamp-based soft deletion (``deleted_at``) for models that need delete-with-restore."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.common.models.user_stamped import authenticated_actor


class TimestampedSoftDeleteQuerySet(models.QuerySet):
    """QuerySet operations for timestamp-based soft deletion."""

    def delete(self) -> tuple[int, dict[str, int]]:
        """Soft-delete active rows without cascading to related objects."""
        deleted_count = self.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
        if not deleted_count:
            return 0, {}
        return deleted_count, {self.model._meta.label: deleted_count}

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Permanently delete rows using Django's normal cascade behavior."""
        return super().delete()

    def deleted(self) -> TimestampedSoftDeleteQuerySet:
        """Return only soft-deleted rows."""
        return self.filter(deleted_at__isnull=False)


class TimestampedSoftDeleteManager(models.Manager.from_queryset(TimestampedSoftDeleteQuerySet)):
    """Default manager that excludes rows marked with ``deleted_at``."""

    def get_queryset(self) -> TimestampedSoftDeleteQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)

    def with_deleted(self) -> TimestampedSoftDeleteQuerySet:
        """Return active and soft-deleted rows."""
        return super().get_queryset()

    def deleted(self) -> TimestampedSoftDeleteQuerySet:
        """Return only soft-deleted rows."""
        return super().get_queryset().filter(deleted_at__isnull=False)


class TimestampedSoftDeleteAllManager(models.Manager.from_queryset(TimestampedSoftDeleteQuerySet)):
    """Unfiltered manager (``all_objects``); queryset deletion remains soft by default."""


class TimestampedSoftDeleteMixin(models.Model):
    """Reusable timestamp-based soft deletion with explicit hard-delete access."""

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = TimestampedSoftDeleteManager()
    all_objects = TimestampedSoftDeleteAllManager()

    class Meta:
        abstract = True

    def soft_delete(self, *, actor=None, using: str | None = None) -> tuple[int, dict[str, int]]:
        if not self.pk:
            raise ValueError(f"{self.__class__.__name__} object can't be soft-deleted before it is saved.")
        if self.deleted_at is not None:
            return 0, {}

        self.deleted_at = timezone.now()
        fields = ["deleted_at"]
        user = authenticated_actor(actor)
        if hasattr(self, "last_modified_by_id") and user is not None:
            self.last_modified_by = user
            fields.append("last_modified_by")
        self.save(actor=actor, using=using, update_fields=tuple(fields))
        return 1, {self._meta.label: 1}

    def restore(self, *, actor=None, using: str | None = None) -> bool:
        if self.deleted_at is None:
            return False

        self.deleted_at = None
        fields = ["deleted_at"]
        user = authenticated_actor(actor)
        if hasattr(self, "last_modified_by_id") and user is not None:
            self.last_modified_by = user
            fields.append("last_modified_by")
        self.save(actor=actor, using=using, update_fields=tuple(fields))
        return True

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
        *,
        actor=None,
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete this row; use ``hard_delete()`` for permanent removal."""
        return self.soft_delete(actor=actor, using=using)

    def hard_delete(self, using: str | None = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """Permanently delete this row using Django's normal cascade behavior."""
        return models.Model.delete(self, using=using, keep_parents=keep_parents)
