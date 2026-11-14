"""Wire names for model fields exposed by generic transports (response standard NAM-2, NAM-3, REL-3).

Technical helper: works on Django field objects and imports no business app.
"""

import re
from collections.abc import Mapping
from typing import Any

from django.db import models

_BOOLEAN_PREFIX = re.compile(r"^(is|has|can)_")


def wire_name(model_field: Any, explicit: Mapping[str, str] | None = None) -> str:
    """Response and request key for ``model_field``.

    An owner-declared name wins. Otherwise a relation keeps its field name (it is rendered as a relation
    object, NAM-8) and a boolean gets the ``is_`` prefix (NAM-2).
    """
    name = model_field.name
    if explicit and name in explicit:
        return explicit[name]
    if isinstance(model_field, models.BooleanField) and not _BOOLEAN_PREFIX.match(name):
        return f"is_{name}"
    return name


def relation_name(instance: Any) -> str:
    """REL-3 display ``name`` of a related row."""
    for attribute in ("name", "project_name", "title", "username"):
        value = getattr(instance, attribute, None)
        if isinstance(value, str) and value:
            return value
    return str(instance)


def relation_object(instance: Any) -> dict[str, Any] | None:
    """REL-3 ``{id, name}`` for a related row, or ``None``."""
    if instance is None:
        return None
    return {"id": instance.pk, "name": relation_name(instance)}
