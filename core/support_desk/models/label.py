"""Free-form ticket labels (Jira-style)."""

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower


class SupportLabel(models.Model):
    """Short tag attached to tickets for cross-cutting grouping (e.g. ``vendor-rma``, ``calibration``)."""

    name = models.CharField(max_length=50)
    color_hex = models.CharField(max_length=7, blank=True, default="", help_text="Optional '#RRGGBB' badge colour.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Support Label"
        verbose_name_plural = "Support Labels"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="unique_support_label_name_ci"),
        ]
        indexes = [
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="support_label_name_trgm_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip().lower()
        super().save(*args, **kwargs)
