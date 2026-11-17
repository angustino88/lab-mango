"""Helpers for generic links to lab resources.

Resources that use multi-table inheritance have one ContentType per class (equipment
had category subclasses until redesign step 6). Generic links (audits, costs,
purchases, service records) therefore always use the *root* resource model, so
the same physical asset is never split across two content types.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import models


def _model_of(resource) -> type[models.Model]:
    model = resource if isinstance(resource, type) else type(resource)
    return model._meta.concrete_model


def resource_root_model(resource) -> type[models.Model]:
    """Return the topmost concrete model of ``resource`` (a model or instance)."""
    model = _model_of(resource)
    parents = model._meta.get_parent_list()
    return parents[-1] if parents else model


def resource_content_type(resource) -> ContentType:
    """ContentType of the root model: use this when WRITING generic links."""
    return ContentType.objects.get_for_model(resource_root_model(resource), for_concrete_model=True)


def resource_content_types(resource) -> list[ContentType]:
    """Root and own ContentTypes: use this when READING, so legacy rows still match."""
    root = resource_content_type(resource)
    own = ContentType.objects.get_for_model(_model_of(resource), for_concrete_model=True)
    return [root] if own.pk == root.pk else [root, own]
