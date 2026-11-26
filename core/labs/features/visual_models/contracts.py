from dataclasses import dataclass
from typing import Protocol


class ModelStorage(Protocol):
    def save(self, content: bytes) -> str: ...
    def delete(self, name: str) -> None: ...


@dataclass(frozen=True)
class AssetDetails:
    """Editable library metadata and the model's placement."""

    name: str
    source_url: str = ""
    license: str = ""
    rotation: float = 0
    surface: float = 1


@dataclass(frozen=True)
class ModelSelection:
    """The model a resource stores and the one it shows after inheriting catalog defaults."""

    id: int
    name: str
    visual_model_id: int | None
    effective_visual_model_id: int | None
    origin: str | None  # "own", the catalog it is inherited from (e.g. "station_type"), or None when none applies
