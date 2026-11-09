"""HTTP behavior shared by the room and station transport adapters."""

from core.common.api.api_views import AppListAPIView
from core.labs.features.base import CommandAPIView


class LocationAPIView(AppListAPIView, CommandAPIView):
    schema_tags = ("Locations",)


__all__ = ["LocationAPIView"]
