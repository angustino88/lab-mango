"""Domain exceptions for the laboratory analytics feature."""
from __future__ import annotations

from core.common.domain.errors import DomainError, InvalidQuery


class AnalyticsError(DomainError):
    """Base exception for all analytics domain errors."""


class AnalyticsValidationError(InvalidQuery, AnalyticsError):
    """Raised when parameters or date intervals violate domain rules."""

    code = "invalid_query"


class StorageQuotaMeasurementError(AnalyticsError):
    """Raised when storage quota measurement data is invalid."""


__all__ = [
    "AnalyticsError",
    "AnalyticsValidationError",
    "StorageQuotaMeasurementError",
]
