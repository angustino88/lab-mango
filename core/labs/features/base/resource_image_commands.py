"""Commands: replace or remove the image of a Labs resource (bench, equipment, license, room, station).

Race guard: the resource row is locked with ``select_for_update`` before the current image name is read,
so two concurrent writes cannot both see the same old file; each write records exactly one change.
Storage I/O (MinIO in production) never runs while the row lock is held: the new file is stored before the
transaction opens, and the replaced file is deleted after commit (best effort; a failed delete leaves an
orphaned object, never a broken reference).
Idempotency: removing an absent image is a no-op. Replacing always stores the new upload under a fresh,
server-generated name (``ResourceImageUploadPath``), so a repeated upload leaves the same observable state
(an image is set) and no orphaned file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from core.labs.models import ResourceChangeLog
from core.labs.models.resource.base.resource import ResourceModel

IMAGE_FIELD = "image"

logger = logging.getLogger(__name__)


class ResourceImageTargetNotFound(Exception):
    """The resource does not exist or is soft-deleted."""


@dataclass(frozen=True)
class ReplaceResourceImageInput:
    resource_id: int
    image: Any


@dataclass(frozen=True)
class RemoveResourceImageInput:
    resource_id: int


def _image_field(model: type[ResourceModel]) -> models.ImageField:
    return cast(models.ImageField, model._meta.get_field(IMAGE_FIELD))


def get_resource_for_image(*, model: type[ResourceModel], resource_id: int) -> ResourceModel:
    resource = model.objects.filter(pk=resource_id).first()
    if resource is None:
        raise ResourceImageTargetNotFound
    return resource


def replace_resource_image(
    *, model: type[ResourceModel], data: ReplaceResourceImageInput, actor: Any = None
) -> ResourceModel:
    """Store ``data.image`` as the resource's image and delete the previous file after commit."""
    resource = get_resource_for_image(model=model, resource_id=data.resource_id)
    field = _image_field(model)
    storage = field.storage
    # Store outside the transaction; the name comes from the field's upload_to (never the client filename).
    stored_name = storage.save(field.generate_filename(resource, data.image.name), data.image)
    try:
        with transaction.atomic():
            locked = _lock(model, data.resource_id)
            old_name = locked.image.name or ""
            locked.image.name = stored_name
            locked.save(actor=actor, update_fields=[IMAGE_FIELD])
            _record_change(locked, actor=actor, old_name=old_name, new_name=stored_name)
            if old_name:
                transaction.on_commit(lambda: _delete_quietly(storage, old_name))
    except BaseException:
        _delete_quietly(storage, stored_name)
        raise
    return locked


def remove_resource_image(
    *, model: type[ResourceModel], data: RemoveResourceImageInput, actor: Any = None
) -> ResourceModel:
    """Clear the resource's image; a resource without an image is left unchanged."""
    storage = _image_field(model).storage
    with transaction.atomic():
        locked = _lock(model, data.resource_id)
        old_name = locked.image.name or ""
        if not old_name:
            return locked
        locked.image.name = None
        locked.save(actor=actor, update_fields=[IMAGE_FIELD])
        _record_change(locked, actor=actor, old_name=old_name, new_name=None)
        transaction.on_commit(lambda: _delete_quietly(storage, old_name))
    return locked


@dataclass(frozen=True)
class ResourceImageCommands:
    """The image use cases bound to one resource model.

    Each feature's application layer owns its binding (e.g. ``bench_images = ResourceImageCommands(Bench)``),
    so its API layer reaches images through the feature, never through ``core.labs.models``.
    """

    model: type[ResourceModel]

    def get(self, *, resource_id: int) -> ResourceModel:
        return get_resource_for_image(model=self.model, resource_id=resource_id)

    def replace(self, *, data: ReplaceResourceImageInput, actor: Any = None) -> ResourceModel:
        return replace_resource_image(model=self.model, data=data, actor=actor)

    def remove(self, *, data: RemoveResourceImageInput, actor: Any = None) -> ResourceModel:
        return remove_resource_image(model=self.model, data=data, actor=actor)


def _lock(model: type[ResourceModel], resource_id: int) -> ResourceModel:
    resource = model.objects.select_for_update(of=("self",)).filter(pk=resource_id).first()
    if resource is None:
        raise ResourceImageTargetNotFound
    return resource


def _record_change(resource: ResourceModel, *, actor: Any, old_name: str, new_name: str | None) -> None:
    if actor is None:
        return  # Same rule as ResourceChangeLogMixin: only authenticated mutations are logged.
    change_log = ResourceChangeLog(
        resource_content_type=ContentType.objects.get_for_model(resource, for_concrete_model=False),
        resource_object_id=str(resource.pk),
        action=ResourceChangeLog.Action.UPDATE,
        field_name=IMAGE_FIELD,
        old_value=old_name or None,
        new_value=new_name,
    )
    change_log.save(actor=actor)


def _delete_quietly(storage: Any, name: str) -> None:
    try:
        storage.delete(name)
    except Exception:  # noqa: BLE001 - cleanup is best effort; the row no longer references the file.
        logger.warning("Could not delete unreferenced resource image %s", name, exc_info=True)
