"""URL module aggregator for the support_desk app."""

from django.urls import include, path

urlpatterns = [
    path("support/", include("core.support_desk.features.tickets.urls")),
]

__all__ = ("urlpatterns",)
