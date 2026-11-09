"""User-to-bench bookmarks; removal deletes the membership, not the bench."""

from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel


class BenchFavorite(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="bench_favorites",
        on_delete=models.CASCADE,
    )
    bench = models.ForeignKey(
        "labs.Bench",
        related_name="favorited_by",
        on_delete=models.CASCADE,
    )

    class Meta:
        app_label = "labs"
        ordering = ("-created", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "bench"),
                name="bench_favorite_user_bench_uniq",
            ),
        ]
        verbose_name = "Bench Favorite"
        verbose_name_plural = "Bench Favorites"

    def __str__(self) -> str:
        return f"BenchFavorite(user_id={self.user_id}, bench_id={self.bench_id})"
