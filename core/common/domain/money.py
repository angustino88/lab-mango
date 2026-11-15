"""Domain rule shared by money that belongs to a parent record (an expense, a purchase)."""

from django.core.exceptions import ValidationError


def check_currency(submitted: str | None, expected: str, *, field: str) -> None:
    """Reject money in another currency than its parent's; ``field`` is the request key it came from (ERR-6)."""
    if submitted is not None and submitted != expected:
        raise ValidationError({field: [f"Use the currency of this record, {expected}."]})


__all__ = ["check_currency"]
