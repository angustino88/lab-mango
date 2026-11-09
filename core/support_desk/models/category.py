"""Support ticket category model."""

from django.db import models
from django.db.models import Q


class SupportCategory(models.Model):
    """Admin-defined ticket category."""

    name = models.CharField(max_length=100)
    code = models.SlugField(
        max_length=50,
        blank=True,
        default="",
        help_text="Stable machine-readable identifier (exposed as 'sku' by the options API).",
    )
    description = models.TextField(blank=True, default="")
    default_team = models.ForeignKey(
        "support_desk.SupportTeam",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_categories",
        help_text="Tickets created in this category are routed to this team unless one is specified.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Category"
        verbose_name_plural = "Support Categories"
        ordering = ["sort_order", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(is_active=True),
                name="unique_active_support_category_name",
            )
        ]

    def __str__(self) -> str:
        return self.name
