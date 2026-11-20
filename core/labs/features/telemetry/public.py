"""Supported telemetry entry points for other features."""

from .contracts import Placement
from .queries import resolve_placement

__all__ = ("Placement", "resolve_placement")
