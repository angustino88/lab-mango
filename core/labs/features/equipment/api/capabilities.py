"""Capabilities exposed for equipment resources."""

ASSIGNABLE = "assignable"
LICENSABLE = "licensable"
STATUS_TRACKING = "status_tracking"
AUDITABLE = "auditable"
BOOKABLE = "bookable"

EQUIPMENT_CAPABILITIES = (
    ASSIGNABLE,
    LICENSABLE,
    STATUS_TRACKING,
    AUDITABLE,
    BOOKABLE,
)

__all__ = (
    "ASSIGNABLE",
    "AUDITABLE",
    "BOOKABLE",
    "EQUIPMENT_CAPABILITIES",
    "LICENSABLE",
    "STATUS_TRACKING",
)
