"""Supported telemetry entry points for other features."""

from .application.ingest import IngestOperation, IngestReading, IngestResult, ingest_samples
from .contracts import Placement, TargetRef
from .queries import resolve_placement
from .queries.latest import CurrentConditions, current_conditions

__all__ = (
    "CurrentConditions",
    "IngestOperation",
    "IngestReading",
    "IngestResult",
    "Placement",
    "TargetRef",
    "current_conditions",
    "ingest_samples",
    "resolve_placement",
)
