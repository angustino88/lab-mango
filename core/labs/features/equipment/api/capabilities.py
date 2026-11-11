"""Capabilities exposed for equipment categories, read from the category's flags."""

ASSIGNABLE = "assignable"
LICENSABLE = "licensable"
STATUS_TRACKING = "status_tracking"
AUDITABLE = "auditable"
BOOKABLE = "bookable"
CALIBRATABLE = "calibratable"
MONITORED = "monitored"

EQUIPMENT_CAPABILITIES = (
    ASSIGNABLE,
    LICENSABLE,
    STATUS_TRACKING,
    AUDITABLE,
    BOOKABLE,
    CALIBRATABLE,
    MONITORED,
)


def category_capabilities(category) -> list[str]:
    """Every unit is licensable, status-tracked and audited; the rest follow the category flags."""
    flags = {
        ASSIGNABLE: category.placeable_on_bench,
        LICENSABLE: True,
        STATUS_TRACKING: True,
        AUDITABLE: True,
        BOOKABLE: category.bookable,
        CALIBRATABLE: category.calibratable,
        MONITORED: category.monitored,
    }
    return [name for name in EQUIPMENT_CAPABILITIES if flags[name]]


__all__ = (
    "ASSIGNABLE",
    "AUDITABLE",
    "BOOKABLE",
    "CALIBRATABLE",
    "EQUIPMENT_CAPABILITIES",
    "LICENSABLE",
    "MONITORED",
    "STATUS_TRACKING",
    "category_capabilities",
)
