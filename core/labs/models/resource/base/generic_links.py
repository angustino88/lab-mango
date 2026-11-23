"""Helpers for generic links to lab resources.

Resources that use multi-table inheritance have one ContentType per class (equipment
had category subclasses until redesign step 6). Generic links (audits, costs,
purchases, service records) therefore always use the *root* resource model, so
the same physical asset is never split across two content types.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError, models
from django.db.models import Q


def _model_of(resource: type[models.Model] | models.Model) -> type[models.Model]:
    model: type[models.Model] = resource if isinstance(resource, type) else type(resource)
    return model._meta.concrete_model or model


def resource_root_model(resource: type[models.Model] | models.Model) -> type[models.Model]:
    """Return the topmost concrete model of ``resource`` (a model or instance)."""
    model = _model_of(resource)
    parents = model._meta.get_parent_list()
    return parents[-1] if parents else model


def resource_content_type(resource: type[models.Model] | models.Model) -> ContentType:
    """ContentType of the root model: use this when WRITING generic links."""
    return ContentType.objects.get_for_model(resource_root_model(resource), for_concrete_model=True)


def resource_content_types(resource: type[models.Model] | models.Model) -> list[ContentType]:
    """Root and own ContentTypes: use this when READING, so legacy rows still match."""
    root = resource_content_type(resource)
    own = ContentType.objects.get_for_model(_model_of(resource), for_concrete_model=True)
    return [root] if own.pk == root.pk else [root, own]


def resource_content_type_filter(
    model: type[models.Model],
    *,
    field_name: str = "resource_content_type",
) -> Q:
    """Return a Q filter matching ``field_name`` for ``model`` and its root.

    Uses Django's public ``ContentType.objects.get_for_models`` (cached in-process by Django)
    so correlated subqueries filter by integer FK PKs instead of joining ``django_content_type``.
    Falls back to ``app_label``/``model`` lookup if DB access is unavailable (e.g. DB-less tests
    or pre-migration schema introspection).
    """
    linked = {resource_root_model(model), model._meta.concrete_model or model}
    try:
        ct_map = ContentType.objects.get_for_models(*linked, for_concrete_models=True)
        ct_ids = sorted({int(ct.pk) for ct in ct_map.values() if ct.pk is not None})
        if len(ct_ids) == 1:
            return Q(**{f"{field_name}_id": ct_ids[0]})
        if ct_ids:
            return Q(**{f"{field_name}_id__in": ct_ids})
    except (RuntimeError, DatabaseError):
        pass
    model_names = sorted(item._meta.model_name for item in linked if item._meta.model_name)
    if len(model_names) == 1:
        return Q(**{f"{field_name}__app_label": model._meta.app_label, f"{field_name}__model": model_names[0]})
    return Q(**{f"{field_name}__app_label": model._meta.app_label, f"{field_name}__model__in": model_names})
