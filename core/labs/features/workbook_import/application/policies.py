"""Who may import a data workbook (owner decision 2026-11-16: Labs administrators only)."""

from typing import Any

from core.users.public import LabsPermission, has_permission


def can_import_workbook(actor: Any) -> bool:
    return bool(getattr(actor, "is_authenticated", False)) and has_permission(actor, LabsPermission.WORKBOOK_IMPORT)


__all__ = ["can_import_workbook"]
