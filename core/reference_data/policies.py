"""Reference import access policy, independent of persistence."""

from typing import Any

from .contracts import ReferenceResource
from .exceptions import ReferencePermissionDenied


def ensure_access(resource: ReferenceResource, actor: Any, *, write: bool = False) -> None:
    if actor is None or not actor.is_authenticated or not actor.is_active:
        raise ReferencePermissionDenied()
    if not write:
        return
    if resource.can_write is not None:
        allowed = resource.can_write(actor)
    else:
        allowed = actor.has_perm(f"{resource.model._meta.app_label}.add_{resource.model._meta.model_name}")
    if not allowed:
        raise ReferencePermissionDenied()
