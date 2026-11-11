from django.contrib.auth.models import Group
from django.db import models
from django.db.models import CharField

LABS_ROLE_CHOICES = [
    ("admin", "Lab admin"),
    ("coord", "Lab coordinator"),
    ("user", "Lab user"),
]


class URSGroup(models.Model):
    class SyncStatus(models.TextChoices):
        APPLIED = "applied", "Applied"
        BLOCKED = "blocked", "Blocked by safety check"
        FAILED = "failed", "Failed"

    group = models.OneToOneField(Group, on_delete=models.SET_NULL, null=True, blank=True)
    urs_group_name = CharField(max_length=255, blank=True, null=True)
    urs_group_id = models.PositiveBigIntegerField()
    active = models.BooleanField(default=True)
    labs_role = models.CharField(
        max_length=10,
        blank=True,
        default="",
        choices=LABS_ROLE_CHOICES,
        verbose_name="Labs role",
        help_text="Labs role granted to members of the linked Django group. Empty grants no Labs role.",
    )
    # Outcome of the most recent sync attempt, shown in Django admin. Written only by the URS sync.
    last_sync_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_sync_status = models.CharField(
        max_length=16, blank=True, default="", choices=SyncStatus.choices, editable=False
    )
    last_sync_message = models.CharField(max_length=500, blank=True, default="", editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["urs_group_id"], name="users_ursgroup_unique_urs_group_id"),
            models.CheckConstraint(
                condition=models.Q(labs_role__in=["", "admin", "coord", "user"]),
                name="users_ursgroup_valid_labs_role",
            ),
            models.CheckConstraint(
                condition=models.Q(last_sync_status__in=["", "applied", "blocked", "failed"]),
                name="users_ursgroup_valid_last_sync_status",
            ),
        ]

    def __str__(self):
        return self.urs_group_name if self.urs_group_name else super().__str__()
