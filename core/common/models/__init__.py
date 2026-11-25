"""Abstract model bases shared across Django apps."""

from core.common.models.outbox import AbstractOutboxLedger
from core.common.models.soft_delete import (
    TimestampedSoftDeleteAllManager,
    TimestampedSoftDeleteManager,
    TimestampedSoftDeleteMixin,
    TimestampedSoftDeleteQuerySet,
)
from core.common.models.user_stamped import UserStampedModel
from core.common.models.validation import validate_for_write

__all__ = [
    "AbstractOutboxLedger",
    "TimestampedSoftDeleteAllManager",
    "TimestampedSoftDeleteManager",
    "TimestampedSoftDeleteMixin",
    "TimestampedSoftDeleteQuerySet",
    "UserStampedModel",
    "validate_for_write",
]
