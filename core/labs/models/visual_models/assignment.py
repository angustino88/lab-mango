from django.db import models

from .asset import VisualModelAsset

SCOPES = ("station_type", "equipment_category", "equipment_model", "equipment", "bench")


class VisualModelAssignment(models.Model):
    """Maps a catalog type or individual resource to a library asset, with per-resource fitting."""

    scope = models.CharField(max_length=24)
    target_key = models.CharField(max_length=80)
    asset = models.ForeignKey(VisualModelAsset, on_delete=models.PROTECT, related_name="assignments")
    # Fitting on top of the asset: extra rotation, scale relative to the fitted box, and offsets as box fractions.
    rotation = models.FloatField(default=0)
    scale = models.FloatField(default=1)
    offset_x = models.FloatField(default=0)
    offset_y = models.FloatField(default=0)
    offset_z = models.FloatField(default=0)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "labs"
        ordering = ("scope", "target_key")
        constraints = [
            models.UniqueConstraint(fields=["scope", "target_key"], name="visual_model_assignment_unique_target"),
            models.CheckConstraint(condition=models.Q(scope__in=SCOPES), name="visual_model_assignment_scope_valid"),
            models.CheckConstraint(
                condition=models.Q(target_key__regex=r"^[1-9][0-9]*$") | models.Q(scope="bench", target_key="*"),
                name="visual_model_assignment_target_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    rotation__gte=-360,
                    rotation__lte=360,
                    scale__gt=0,
                    scale__lte=2,
                    offset_x__gte=-1,
                    offset_x__lte=1,
                    offset_y__gte=-1,
                    offset_y__lte=1,
                    offset_z__gte=-1,
                    offset_z__lte=1,
                ),
                name="visual_model_assignment_fit_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="visual_model_assignment_version_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scope}/{self.target_key}"
