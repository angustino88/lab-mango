"""Canned responses (macros) agents can insert into replies."""

from django.conf import settings
from django.db import models
from django.db.models import Q


class CannedResponse(models.Model):
    """Reusable reply template. Placeholders: ``{{requester_name}}``, ``{{ticket_key}}``, ``{{agent_name}}``."""

    title = models.CharField(max_length=120)
    body = models.TextField()
    team = models.ForeignKey(
        "support_desk.SupportTeam",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="canned_responses",
        help_text="Restrict to one team's agents; empty means available to every agent.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Canned Response"
        verbose_name_plural = "Canned Responses"
        ordering = ["title", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "team"],
                condition=Q(is_active=True),
                name="unique_active_canned_response_title_team",
            ),
        ]

    def __str__(self) -> str:
        return self.title
