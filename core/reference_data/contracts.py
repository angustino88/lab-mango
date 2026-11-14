"""Owner-supplied definitions for reference import operations."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReferenceResource:
    key: str
    model: Any
    fields: tuple[str, ...]
    identity: tuple[str, ...]
    label: str = "name"
    # Owner-declared wire names ``((model_field, api_key), ...)`` where the default naming does not fit
    # the response standard (for example dates that must end in ``_date``, NAM-3).
    wire_names: tuple[tuple[str, str], ...] = ()
    # Owner-supplied write rule ``(actor) -> bool``. None keeps the default: the model's Django
    # ``add_<model>`` permission. The framework never imports the owner's role model.
    can_write: Callable[[Any], bool] | None = field(default=None, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class CreateReferenceInput:
    values: dict[str, Any]
    idempotency_key: str


@dataclass(frozen=True)
class ReferenceResult:
    data: dict[str, Any]
    replayed: bool = False
