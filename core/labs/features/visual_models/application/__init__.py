"""Unique target constraint and locked version checks guard concurrent catalog edits."""

import math
import re

from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.labs.models.visual_models import VisualModel
from core.users.public import LabsPermission, has_permission

from ..contracts import ModelStorage, SaveModelInput
from ..exceptions import InvalidModel, ModelConflict
from ..validation import validate_glb

SCOPES = ("station_type", "equipment_category", "equipment_model", "equipment", "bench")


def ensure_editor(actor):
    if not has_permission(actor, LabsPermission.LAB_OPERATIONS_MANAGE):
        raise PermissionDenied


def save_model(data: SaveModelInput, *, actor, storage: ModelStorage) -> VisualModel:
    ensure_editor(actor)
    if data.scope not in SCOPES or not (
        re.fullmatch(r"[1-9][0-9]*", data.target_key) or (data.scope == "bench" and data.target_key == "*")
    ):
        raise InvalidModel("Select a supported catalog type or resource.")
    if not all(
        math.isfinite(value)
        for value in (data.scale, data.rotation, data.surface, data.offset_x, data.offset_y, data.offset_z)
    ):
        raise InvalidModel("Placement values must be finite numbers.")
    if any(abs(value) > 1 for value in (data.offset_x, data.offset_y, data.offset_z)):
        raise InvalidModel("Offsets must be between -1 and 1.")
    if not 0 < data.scale <= 2 or not 0 <= data.surface <= 1 or not -360 <= data.rotation <= 360:
        raise InvalidModel("The placement settings are out of range.")
    if data.content is not None:
        validate_glb(data.content)
    stored = storage.save(data.content) if data.content is not None else None
    try:
        with transaction.atomic():
            # The unique constraint makes get_or_create safe when two editors create a target.
            model, created = VisualModel.objects.select_for_update().get_or_create(
                scope=data.scope,
                target_key=data.target_key,
                defaults={"name": data.name, "file": stored or ""},
            )
            if (0 if created else model.version) != data.expected_version:
                raise ModelConflict
            if not stored and not model.file:
                raise InvalidModel("Attach a GLB file before saving.")
            old = model.file.name
            for field in (
                "name",
                "rotation",
                "scale",
                "surface",
                "source_url",
                "license",
                "offset_x",
                "offset_y",
                "offset_z",
            ):
                setattr(model, field, getattr(data, field))
            if stored:
                model.file.name = stored
            model.version = 1 if created else model.version + 1
            model.save()
            if old and stored and old != stored:
                transaction.on_commit(lambda: storage.delete(old))
    except BaseException:
        if stored:
            storage.delete(stored)
        raise
    return model


def remove_model(*, scope: str, target_key: str, expected_version: int, actor, storage: ModelStorage):
    ensure_editor(actor)
    with transaction.atomic():
        model = VisualModel.objects.select_for_update().filter(scope=scope, target_key=target_key).first()
        if model is None:
            raise ModelConflict
        if model.version != expected_version:
            raise ModelConflict
        name = model.file.name
        model.delete()
        if name:
            transaction.on_commit(lambda: storage.delete(name))
