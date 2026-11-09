"""Stable business exceptions for agent identity workflows."""


class AgentEnrollmentConflict(Exception):
    """Raised when an equipment item already has an active or pending agent."""


class AgentEquipmentNotFound(Exception):
    """Raised when the named computing equipment does not exist or is deleted."""


class EnrollmentGrantInvalid(Exception):
    """Raised when an enrollment grant is unknown, expired, used, or revoked."""


class AgentProofInvalid(Exception):
    """Raised when the presented device key cannot prove possession."""


class AgentRequestUnauthenticated(Exception):
    """Raised when a signed agent request cannot be attributed to an active identity.

    Callers must not reveal which check failed (unknown agent, revoked, bad signature, stale
    timestamp or replayed nonce) to the client.
    """
