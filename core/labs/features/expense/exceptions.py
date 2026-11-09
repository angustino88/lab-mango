"""Stable expense business errors."""


from core.common.domain.errors import Conflict


class ExpenseConflict(Conflict):
    """Raised when an expense write conflicts with the current expense state."""

    code = "expense_conflict"


__all__ = ["ExpenseConflict"]
