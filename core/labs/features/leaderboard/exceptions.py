"""Business exceptions for the leaderboard feature."""
from __future__ import annotations

from core.common.domain.errors import DomainError, Forbidden, InvalidQuery, NotFound


class LeaderboardError(DomainError):
    """Base error for all leaderboard domain issues."""


class LeaderboardValidationError(InvalidQuery, LeaderboardError):
    """Invalid query or request parameters passed to leaderboard."""

    code = "invalid_query"


class ResourceNotFoundError(NotFound, LeaderboardError):
    """Requested laboratory or user resource was not found."""

    code = "not_found"


class AssessmentAccessDenied(Forbidden, LeaderboardError):
    """The viewer may not read this assessment: only their own, unless they are lab staff."""

    code = "permission_denied"
    default_message = "Only lab coordinators and administrators can see this assessment."


__all__ = [
    "AssessmentAccessDenied",
    "LeaderboardError",
    "LeaderboardValidationError",
    "ResourceNotFoundError",
]
