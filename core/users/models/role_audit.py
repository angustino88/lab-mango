"""Append-only record of every change to who holds which access (ISO 27001 A.5.15/A.5.18).

PostgreSQL rejects UPDATE and DELETE on this table (migration 0006). People are stored as id plus a
username snapshot, not foreign keys, so deleting a user never needs to touch (or lose) their history.
"""

from django.db import models
from django.utils import timezone

from .user import User


class RoleAuditEvent(models.Model):
    class EventType(models.TextChoices):
        URS_GROUP_CREATED = "urs_group_created", "URS group created"
        URS_GROUP_CHANGED = "urs_group_changed", "URS group changed"
        URS_GROUP_DELETED = "urs_group_deleted", "URS group deleted"
        USER_PRIVILEGES_CHANGED = "user_privileges_changed", "User privileges changed"
        GROUP_PERMISSIONS_CHANGED = "group_permissions_changed", "Group permissions changed"
        URS_SYNC_MEMBERSHIP = "urs_sync_membership", "URS sync changed group members"
        USER_ACTIVITY_CHANGED = "user_activity_changed", "User activated or deactivated"
        ENTRA_IDENTITY_BOUND = "entra_identity_bound", "Entra identity linked"
        ENTRA_IDENTITY_UNLINKED = "entra_identity_unlinked", "Entra identity unlinked"

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    event_type = models.CharField(max_length=40, choices=EventType.choices, editable=False)
    actor_id = models.BigIntegerField(null=True, blank=True, editable=False)
    actor_label = models.CharField(max_length=150, editable=False, help_text="Username, or the system job name.")
    target_user_id = models.BigIntegerField(null=True, blank=True, db_index=True, editable=False)
    target_label = models.CharField(max_length=150, blank=True, default="", editable=False)
    subject = models.CharField(max_length=255, blank=True, default="", editable=False)
    changes = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        verbose_name = "role change"
        verbose_name_plural = "role audit log"
        ordering = ("-occurred_at", "-id")
        indexes = [models.Index(fields=["event_type", "occurred_at"], name="users_roleaudit_type_time")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event_type__in=[
                        "urs_group_created",
                        "urs_group_changed",
                        "urs_group_deleted",
                        "user_privileges_changed",
                        "group_permissions_changed",
                        "urs_sync_membership",
                        "user_activity_changed",
                        "entra_identity_bound",
                        "entra_identity_unlinked",
                    ]
                ),
                name="users_roleaudit_valid_event_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_event_type_display()} by {self.actor_label} at {self.occurred_at:%Y-%m-%d %H:%M}"


class PrivilegedUser(User):
    """Proxy of ``User`` for the read-only access review screen in Django admin."""

    class Meta:
        proxy = True
        verbose_name = "privileged user"
        verbose_name_plural = "access review"
