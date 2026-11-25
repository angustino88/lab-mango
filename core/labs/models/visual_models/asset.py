from django.db import models


class VisualModelAsset(models.Model):
    """A GLB file in the shared 3D model library, uploaded once and reused by many resources."""

    name = models.CharField(max_length=160)
    file = models.FileField(upload_to="visual_models")
    sha256 = models.CharField(max_length=64, unique=True)
    size = models.PositiveIntegerField()
    source_url = models.URLField(blank=True)
    license = models.CharField(max_length=255, blank=True)
    # Model-intrinsic placement: turns the export to face forward and marks the working surface height.
    rotation = models.FloatField(default=0)
    surface = models.FloatField(default=1)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "labs"
        ordering = ("name", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sha256__regex=r"^[0-9a-f]{64}$"), name="visual_model_asset_sha256_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(rotation__gte=-360, rotation__lte=360, surface__gte=0, surface__lte=1),
                name="visual_model_asset_placement_bounds",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="visual_model_asset_version_positive"),
        ]

    def __str__(self) -> str:
        return self.name
