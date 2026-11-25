from dataclasses import dataclass
from typing import Protocol


class ModelStorage(Protocol):
    def save(self, content: bytes) -> str: ...
    def delete(self, name: str) -> None: ...


@dataclass(frozen=True)
class SaveModelInput:
    scope: str
    target_key: str
    name: str
    content: bytes | None
    expected_version: int
    rotation: float = 0
    scale: float = 1
    surface: float = 1
    offset_x: float = 0
    offset_y: float = 0
    offset_z: float = 0
    source_url: str = ""
    license: str = ""
