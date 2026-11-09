"""Support team (queue / resolver group) model."""

from django.conf import settings
from django.db import models
from django.db.models import Q


class SupportTeam(models.Model):
    """Resolver group that owns a queue of tickets (e.g. "CAN Tooling", "Lab Infrastructure")."""

    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50, help_text="Stable machine-readable identifier used by the options API.")
    description = models.TextField(blank=True, default="")
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="led_support_teams",
        help_text="Receives SLA breach escalations for tickets owned by this team.",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="support_teams",
        help_text="Agents who work this team's queue and are notified about new tickets.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Team"
        verbose_name_plural = "Support Teams"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_active=True),
                name="unique_active_support_team_code",
            ),
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(is_active=True),
                name="unique_active_support_team_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name
