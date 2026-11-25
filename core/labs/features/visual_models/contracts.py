from dataclasses import dataclass
from typing import Protocol


class ModelStorage(Protocol):
    def save(self, content: bytes) -> str: ...
    def delete(self, name: str) -> None: ...


@dataclass(frozen=True)
class AssetDetails:
    """Editable library metadata and the model-intrinsic placement defaults."""

    name: str
    source_url: str = ""
    license: str = ""
    rotation: float = 0
    surface: float = 1


@dataclass(frozen=True)
class AssignmentFit:
    """Per-resource fitting applied on top of the asset's own placement."""

    asset_id: int
    rotation: float = 0
    scale: float = 1
    offset_x: float = 0
    offset_y: float = 0
    offset_z: float = 0
