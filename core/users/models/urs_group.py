from django.contrib.auth.models import Group
from django.db import models
from django.db.models import CharField

LABS_ROLE_CHOICES = [
    ("admin", "Lab admin"),
    ("coord", "Lab coordinator"),
    ("user", "Lab user"),
]


class URSGroup(models.Model):
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

    def __str__(self):
        return self.urs_group_name if self.urs_group_name else super().__str__()
