"""Stable business errors for license workflows."""


from core.common.domain.errors import Conflict


class LicenseAlreadyAssigned(Conflict):
    """Raised when an active license assignment already exists."""

    code = "license_already_assigned"
    default_message = "The license already has an active assignment."


class InvalidLicenseStatus(Conflict):
    """Raised when a requested license status is not supported."""

    code = "invalid_state_transition"
    default_message = "The requested license status is not allowed."


__all__ = ["InvalidLicenseStatus", "LicenseAlreadyAssigned"]
