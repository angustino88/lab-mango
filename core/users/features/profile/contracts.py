"""Stable profile DTOs. Types only; no ORM, settings or framework imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActorContext:
    """Identity of the caller, constructed by the API adapter."""

    user_id: int


@dataclass(frozen=True)
class UploadedImage:
    """Neutral view of an uploaded avatar file."""

    name: str
    size: int
    content_type: str | None
