"""Inputs and results for user lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserLifecycleResult:
    changed: bool
    user_id: int
    identity_id: int | None = None


@dataclass(frozen=True, slots=True)
class SetUserActiveInput:
    user_id: int
    is_active: bool


@dataclass(frozen=True, slots=True)
class BindEntraIdentityInput:
    user_id: int
    tenant_id: UUID
    object_id: UUID


@dataclass(frozen=True, slots=True)
class ReplaceEntraIdentityInput:
    user_id: int
    tenant_id: UUID
    object_id: UUID


@dataclass(frozen=True, slots=True)
class UnlinkEntraIdentityInput:
    user_id: int


@dataclass(frozen=True, slots=True)
class DeleteUserInput:
    user_id: int
