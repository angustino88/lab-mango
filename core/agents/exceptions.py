"""Stable business exceptions for agent identity workflows."""


class AgentEnrollmentConflict(Exception):
    """Raised when an equipment item already has an active or pending agent."""


class EnrollmentGrantInvalid(Exception):
    """Raised when an enrollment grant is unknown, expired, used, or revoked."""


class AgentProofInvalid(Exception):
    """Raised when the presented device key cannot prove possession."""
