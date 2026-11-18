"""Neutral, immutable principal scope for application commands."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActorContext:
    key: str
    kind: str
    capabilities: frozenset[str]
    equipment_ids: frozenset[int]
