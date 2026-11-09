"""Atomic command boundary and field assignment shared by application layers (ADR 001, D2)."""

from collections.abc import Callable, Collection, Iterable, Mapping
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

P = ParamSpec("P")
R = TypeVar("R")

_DEFAULT_CONFLICT_MESSAGE = "The write conflicts with an existing resource or reference."


def constraint_name(error: IntegrityError) -> str | None:
    """Return the PostgreSQL constraint name behind ``error``, when the driver reports one."""
    cause = error.__cause__ or error
    return getattr(getattr(cause, "diag", None), "constraint_name", None)


def atomic_command(
    conflict: type[Exception],
    *,
    constraints: Collection[str] | None = None,
    message: str = _DEFAULT_CONFLICT_MESSAGE,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Run the command in one transaction and translate constraint failures into ``conflict``.

    ``constraints`` lists the constraint names that represent a business conflict. Any other
    ``IntegrityError`` is re-raised unchanged. ``constraints=None`` keeps the legacy behavior of
    translating every ``IntegrityError``; new commands should name their constraints.
    ``ProtectedError`` (deleting a referenced row) is always a conflict.
    """

    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                with transaction.atomic():
                    return function(*args, **kwargs)
            except ProtectedError as exc:
                raise conflict(message) from exc
            except IntegrityError as exc:
                if constraints is not None and constraint_name(exc) not in constraints:
                    raise
                raise conflict(message) from exc

        return wrapped

    return decorator


def apply_fields(instance: Any, data: Mapping[str, Any], allowed: Iterable[str]) -> None:
    """Set allowlisted attributes on ``instance``; unknown keys raise a field-level ValidationError."""
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValidationError({field: "This field is not writable." for field in sorted(unknown)})
    for field, value in data.items():
        setattr(instance, field, value)


__all__ = ["apply_fields", "atomic_command", "constraint_name"]
