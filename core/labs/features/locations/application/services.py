"""Atomic boundary and field assignment for location commands (shared implementation in common)."""

from core.common.db.transactions import apply_fields, atomic_command

__all__ = ["apply_fields", "atomic_command"]
