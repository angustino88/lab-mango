"""Supported telemetry entry points for other features."""

from .contracts import Placement, TargetRef
from .queries import resolve_placement

__all__ = ("Placement", "TargetRef", "resolve_placement")
