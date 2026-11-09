from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from django.db import models


class ReferenceMode(Enum):
    """Controls whether declarations are re-applied after their initial run."""

    SEED_ONCE = "seed_once"
    ENSURE_PRESENT = "ensure_present"


@dataclass(frozen=True)
class ReferenceList:
    """Declarative initial rows for one app-owned reference list."""

    key: str
    model: type[models.Model]
    identity: str
    mode: ReferenceMode
    rows: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("Reference list key must not be empty.")
        if not self.identity.strip():
            raise ValueError("Reference list identity field must not be empty.")
