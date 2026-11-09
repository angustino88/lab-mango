"""Business exceptions for the leaderboard feature."""
from __future__ import annotations

from core.common.domain.errors import DomainError, InvalidQuery, NotFound


class LeaderboardError(DomainError):
    """Base error for all leaderboard domain issues."""


class LeaderboardValidationError(InvalidQuery, LeaderboardError):
    """Invalid query or request parameters passed to leaderboard."""

    code = "invalid_query"


class ResourceNotFoundError(NotFound, LeaderboardError):
    """Requested laboratory or user resource was not found."""

    code = "not_found"


__all__ = [
    "LeaderboardError",
    "LeaderboardValidationError",
    "ResourceNotFoundError",
]
