"""Record role and privilege changes in the append-only ``RoleAuditEvent`` table.

Callers record inside the same transaction as the change, so an event exists exactly when the change
committed. Nothing here grants or checks access.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from core.users.models import RoleAuditEvent

SYSTEM_URS_SYNC = "system:urs-sync"


def record_role_event(
    event_type: str,
    *,
    actor: Any = None,
    actor_label: str = "",
    target: Any = None,
    subject: str = "",
    changes: Mapping[str, Any] | None = None,
) -> RoleAuditEvent:
    """Append one event. ``actor`` is the user who acted; system jobs pass ``actor_label`` instead."""
    return RoleAuditEvent.objects.create(
        event_type=event_type,
        actor_id=getattr(actor, "pk", None),
        actor_label=actor_label or getattr(actor, "username", "") or "unknown",
        target_user_id=getattr(target, "pk", None),
        target_label=getattr(target, "username", "") if target is not None else "",
        subject=subject[:255],
        changes=dict(changes or {}),
    )


def diff(before: Mapping[str, Any], after: Mapping[str, Any], fields: Iterable[str]) -> dict[str, dict[str, Any]]:
    """``{field: {"before": old, "after": new}}`` for the fields whose value changed."""
    return {
        name: {"before": before.get(name), "after": after.get(name)}
        for name in fields
        if before.get(name) != after.get(name)
    }


__all__ = ["SYSTEM_URS_SYNC", "diff", "record_role_event"]
