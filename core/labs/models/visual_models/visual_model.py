from django.db import models


class VisualModel(models.Model):
    """Shared 3D representation assigned to a catalog type or resource."""

    scope = models.CharField(max_length=24)
    target_key = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    file = models.FileField(upload_to="visual_models")
    rotation = models.FloatField(default=0)
    scale = models.FloatField(default=1)
    offset_x = models.FloatField(default=0)
    offset_y = models.FloatField(default=0)
    offset_z = models.FloatField(default=0)
    surface = models.FloatField(default=1)
    source_url = models.URLField(blank=True)
    license = models.CharField(max_length=255, blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "labs"
        ordering = ("scope", "target_key")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    scope__in=["station_type", "equipment_category", "equipment_model", "equipment", "bench"]
                ),
                name="visual_model_scope_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(target_key__regex=r"^[1-9][0-9]*$") | models.Q(scope="bench", target_key="*"),
                name="visual_model_target_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    offset_x__gte=-1,
                    offset_x__lte=1,
                    offset_y__gte=-1,
                    offset_y__lte=1,
                    offset_z__gte=-1,
                    offset_z__lte=1,
                    rotation__gte=-360,
                    rotation__lte=360,
                ),
                name="visual_model_transform_bounds",
            ),
            models.UniqueConstraint(fields=["scope", "target_key"], name="visual_model_unique_target"),
            models.CheckConstraint(condition=models.Q(scale__gt=0, scale__lte=2), name="visual_model_scale_bounds"),
            models.CheckConstraint(
                condition=models.Q(surface__gte=0, surface__lte=1), name="visual_model_surface_bounds"
            ),
        ]
