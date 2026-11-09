"""Support ticket priority model."""

from django.db import models
from django.db.models import Q


class SupportPriority(models.Model):
    """Admin-defined ticket priority."""

    name = models.CharField(max_length=50)
    code = models.SlugField(max_length=50, blank=True, default="", help_text="Stable machine-readable identifier.")
    color_hex = models.CharField(max_length=7, blank=True, default="", help_text="Optional '#RRGGBB' badge colour.")
    rank = models.PositiveIntegerField(help_text="Lower rank indicates higher urgency (1=Critical)")
    response_target_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="SLA: minutes allowed until the first agent response (empty = no target).",
    )
    resolution_target_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="SLA: minutes allowed until the ticket is resolved (empty = no target).",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Priority"
        verbose_name_plural = "Support Priorities"
        ordering = ["rank", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(is_active=True),
                name="unique_active_support_priority_name",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} (rank {self.rank})"
