"""Domain exceptions for the dashboard feature."""


from core.common.domain.errors import DomainError, InvalidQuery, NotFound


class DashboardError(DomainError):
    """Base domain exception for dashboard operations."""

    code = "dashboard_error"


class DashboardResourceNotFound(NotFound, DashboardError):
    """Raised when a requested dashboard resource or bench cannot be found."""

    code = "not_found"


class DashboardFilterError(InvalidQuery, DashboardError):
    """Raised when dashboard query filters are contradictory or invalid."""

    code = "dashboard_filter_error"


__all__ = (
    "DashboardError",
    "DashboardFilterError",
    "DashboardResourceNotFound",
)
