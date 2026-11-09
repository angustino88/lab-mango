"""Domain exceptions for the Support Desk application.

Every class is a ``core.common.domain.errors`` category, so the global API exception handler maps it
to the standard error envelope. Views never catch these errors.
"""

from core.common.domain.errors import Conflict, DomainError, Forbidden, NotFound, VersionConflict


class SupportDeskError(DomainError):
    """Base exception for all Support Desk domain errors. Unclassified errors map to 422."""


class TicketNotFoundError(NotFound, SupportDeskError):
    """Raised when a ticket cannot be located."""

    code = "not_found"


class ResourceNotFoundError(NotFound, SupportDeskError):
    """Raised when a requested resource is not found."""

    code = "not_found"


class RecordNotFoundError(NotFound, SupportDeskError):
    """Raised when a comment, attachment, or configuration record cannot be located."""

    code = "not_found"


class InvalidStatusTransitionError(SupportDeskError):
    """Raised when a status transition is not permitted by the configured workflow."""


class MissingTransitionReasonError(SupportDeskError):
    """Raised when a transition requires a reason that was not supplied."""


class MissingResolutionSummaryError(SupportDeskError):
    """Raised when resolving a ticket without providing a resolution summary."""


class ReopenWindowExpiredError(SupportDeskError):
    """Raised when a requester attempts to reopen a ticket past the allowed window."""


class PermissionDeniedError(Forbidden, SupportDeskError):
    """Raised when an actor lacks the required role or ownership for an action."""

    code = "permission_denied"


class DuplicateResourceLinkError(Conflict, SupportDeskError):
    """Raised when linking a resource that is already actively linked to the ticket."""


class ResourceAccessDeniedError(Forbidden, SupportDeskError):
    """Raised when an actor attempts to link a resource they cannot access."""

    code = "permission_denied"


class ConcurrencyConflictError(VersionConflict, SupportDeskError):
    """Raised when optimistic lock verification fails due to concurrent modifications."""


class CommentEditWindowExpiredError(SupportDeskError):
    """Raised when attempting to edit or delete a comment after its edit window closed."""


class CommentAuthorMismatchError(SupportDeskError):
    """Raised when a user attempts to edit or delete another author's comment."""


class CommentImmutableVisibilityError(SupportDeskError):
    """Raised when attempting to change the visibility of an existing comment."""


class TicketCreationDisabledError(SupportDeskError):
    """Raised when ticket creation is attempted before categories and priorities are defined."""


class AttachmentSizeLimitExceededError(SupportDeskError):
    """Raised when an uploaded file exceeds the configured size limit."""


class AttachmentTypeNotAllowedError(SupportDeskError):
    """Raised when an uploaded file's extension or type is disallowed."""


class AttachmentCountLimitExceededError(SupportDeskError):
    """Raised when adding an attachment exceeds the per-ticket limit."""


class AttachmentRestrictedError(Forbidden, SupportDeskError):
    """Raised when an unauthorized user attempts to access a restricted attachment."""

    code = "permission_denied"


class AttachmentScanPendingError(Conflict, SupportDeskError):
    """Raised when downloading an attachment whose malware scan has not finished."""


class AttachmentInfectedError(SupportDeskError):
    """Raised when attempting to access a file identified as infected."""


class ImmutableActivityError(SupportDeskError):
    """Raised when an update or delete operation is attempted on ticket activity logs."""


class ConfigurationInUseError(Conflict, SupportDeskError):
    """Raised when attempting to delete a category, priority, or status currently in use."""


class InvalidTicketLinkError(SupportDeskError):
    """Raised when a ticket link is invalid (self reference, unknown ticket, unsupported type)."""


class DuplicateTicketLinkError(Conflict, SupportDeskError):
    """Raised when the same link already exists between two tickets."""


class InvalidParentTicketError(SupportDeskError):
    """Raised when a parent assignment would create a cycle or more than one level of nesting."""


class CsatNotAllowedError(SupportDeskError):
    """Raised when a satisfaction rating cannot be submitted (disabled, not resolved, or window expired)."""


class InvalidFieldValueError(SupportDeskError):
    """Raised when a supplied field value is not one of the allowed choices."""
