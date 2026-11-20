"""Read-only telemetry selectors."""

from .devices import get_channel, get_device, list_devices, list_source_channels, target_overview
from .placement import resolve_placement
from .profiles import get_device_profile, list_device_profiles, list_metrics

__all__ = [
    "get_channel",
    "get_device",
    "get_device_profile",
    "list_device_profiles",
    "list_devices",
    "list_metrics",
    "list_source_channels",
    "resolve_placement",
    "target_overview",
]
