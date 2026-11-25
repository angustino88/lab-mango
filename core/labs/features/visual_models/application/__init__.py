"""Library and selection writes. The unique sha256, row locks and version checks guard concurrent editors."""

import hashlib
import math

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from core.common.models.user_stamped import UserStampedModel
from core.labs.models.visual_models import VisualModelAsset
from core.users.public import LabsPermission, has_permission

from ..contracts import AssetDetails, ModelSelection, ModelStorage
from ..exceptions import AssetInUse, InvalidModel, ModelConflict, ModelNotFound
from ..queries import asset_usage, get_selection
from ..targets import TARGETS
from ..validation import validate_glb


def ensure_editor(actor):
    if not has_permission(actor, LabsPermission.LAB_OPERATIONS_MANAGE):
        raise PermissionDenied


def _check_finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise InvalidModel("Placement values must be finite numbers.")


def _check_details(details: AssetDetails) -> None:
    _check_finite(details.rotation, details.surface)
    if not -360 <= details.rotation <= 360 or not 0 <= details.surface <= 1:
        raise InvalidModel("The model placement defaults are out of range.")


def _apply_details(asset: VisualModelAsset, details: AssetDetails) -> bool:
    changed = False
    for field in ("name", "source_url", "license", "rotation", "surface"):
        value = getattr(details, field)
        if getattr(asset, field) != value:
            setattr(asset, field, value)
            changed = True
    return changed


def upload_asset(
    content: bytes, details: AssetDetails, *, actor, storage: ModelStorage
) -> tuple[VisualModelAsset, bool]:
    """Add a GLB to the library. Returns ``(asset, created)``; identical bytes reuse the existing asset."""
    ensure_editor(actor)
    _check_details(details)
    validate_glb(content)
    digest = hashlib.sha256(content).hexdigest()
    existing = VisualModelAsset.objects.filter(sha256=digest).first()
    if existing is not None:
        return existing, False
    stored = storage.save(content)
    try:
        with transaction.atomic():
            asset = VisualModelAsset(file=stored, sha256=digest, size=len(content))
            _apply_details(asset, details)
            asset.save()
    except IntegrityError:
        # A concurrent upload of the same bytes won the unique sha256 constraint.
        storage.delete(stored)
        existing = VisualModelAsset.objects.filter(sha256=digest).first()
        if existing is None:
            raise
        return existing, False
    except BaseException:
        storage.delete(stored)
        raise
    return asset, True


def update_asset(asset_id: int, details: AssetDetails, *, expected_version: int, actor) -> VisualModelAsset:
    ensure_editor(actor)
    _check_details(details)
    with transaction.atomic():
        asset = VisualModelAsset.objects.select_for_update().filter(pk=asset_id).first()
        if asset is None:
            raise ModelNotFound
        if asset.version != expected_version:
            raise ModelConflict
        if _apply_details(asset, details):
            asset.version += 1
            asset.save()
    return asset


def delete_asset(asset_id: int, *, expected_version: int, actor, storage: ModelStorage) -> None:
    ensure_editor(actor)
    with transaction.atomic():
        asset = VisualModelAsset.objects.select_for_update().filter(pk=asset_id).first()
        if asset is None:
            raise ModelNotFound
        if asset.version != expected_version:
            raise ModelConflict
        # Resources reference the asset with PROTECT; this check gives a clear error before the database does.
        usage = asset_usage(asset.pk)
        if usage:
            raise AssetInUse(usage)
        name = asset.file.name
        asset.delete()
        if name:
            transaction.on_commit(lambda: storage.delete(name))


def select_visual_model(segment: str, pk: int, asset_id: int | None, *, actor) -> ModelSelection:
    """Store ``asset_id`` (or clear it with None) on one resource. Last write wins; the row lock serializes writers."""
    ensure_editor(actor)
    target = TARGETS.get(segment)
    if target is None:
        raise ModelNotFound
    with transaction.atomic():
        row = target.queryset().select_for_update(of=("self",)).filter(pk=pk).first()
        if row is None:
            raise ModelNotFound
        # Lock the asset so it cannot be deleted while it is being assigned.
        if asset_id is not None and not VisualModelAsset.objects.select_for_update().filter(pk=asset_id).exists():
            raise InvalidModel("Select a model from the library.")
        if row.visual_model_id != asset_id:
            row.visual_model_id = asset_id
            fields = ["visual_model"] + [name for name in ("updated_at",) if hasattr(row, name)]
            if isinstance(row, UserStampedModel):
                row.save(update_fields=fields, actor=actor)
            else:
                row.save(update_fields=fields)
    selection = get_selection(segment, pk)
    assert selection is not None
    return selection
