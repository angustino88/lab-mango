"""Owner-supplied definitions for reference import operations."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceResource:
    key: str
    model: Any
    fields: tuple[str, ...]
    identity: tuple[str, ...]
    label: str = "name"


@dataclass(frozen=True)
class CreateReferenceInput:
    values: dict[str, Any]
    idempotency_key: str


@dataclass(frozen=True)
class ReferenceResult:
    data: dict[str, Any]
    replayed: bool = False
