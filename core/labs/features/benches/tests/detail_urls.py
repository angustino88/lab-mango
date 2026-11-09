"""Isolated canonical bench URLs for focused tests, without unrelated features."""

from django.urls import include, path

urlpatterns = [path("api/labs/", include("core.labs.features.benches.urls"))]
