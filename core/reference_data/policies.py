"""Reference import access policy, independent of persistence.

Reads need an active, signed-in user (the owning app's endpoint policy narrows them further). Writes need the
owner's write rule (``ReferenceResource.can_write``), normally a Labs permission check; a resource without one
is read-only. Django model permissions (``add_<model>``) grant nothing here (one authorization system,
role-based-access-redesign.md D3).
"""

from typing import Any

from .contracts import ReferenceResource
from .exceptions import ReferencePermissionDenied


def ensure_access(resource: ReferenceResource, actor: Any, *, write: bool = False) -> None:
    if actor is None or not actor.is_authenticated or not actor.is_active:
        raise ReferencePermissionDenied()
    if not write:
        return
    if resource.can_write is None or not resource.can_write(actor):
        raise ReferencePermissionDenied()
