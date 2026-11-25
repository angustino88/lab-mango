"""Library writes. Unique sha256/target constraints and locked version checks guard concurrent editors."""

import hashlib
import math
import re

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from core.labs.models.visual_models import VISUAL_MODEL_SCOPES, VisualModelAsset, VisualModelAssignment
from core.users.public import LabsPermission, has_permission

from ..contracts import AssetDetails, AssignmentFit, ModelStorage
from ..exceptions import AssetInUse, InvalidModel, ModelConflict, ModelNotFound
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
        # Assignments reference the asset with PROTECT; this check gives a clear error before the database does.
        usage = asset.assignments.count()
        if usage:
            raise AssetInUse(usage)
        name = asset.file.name
        asset.delete()
        if name:
            transaction.on_commit(lambda: storage.delete(name))


def _check_target(scope: str, target_key: str) -> None:
    if scope not in VISUAL_MODEL_SCOPES or not (
        re.fullmatch(r"[1-9][0-9]*", target_key) or (scope == "bench" and target_key == "*")
    ):
        raise InvalidModel("Select a supported catalog type or resource.")


def assign_model(
    scope: str, target_key: str, fit: AssignmentFit, *, expected_version: int, actor
) -> VisualModelAssignment:
    """Create (``expected_version`` 0) or update the assignment for one target."""
    ensure_editor(actor)
    _check_target(scope, target_key)
    _check_finite(fit.rotation, fit.scale, fit.offset_x, fit.offset_y, fit.offset_z)
    if any(abs(value) > 1 for value in (fit.offset_x, fit.offset_y, fit.offset_z)):
        raise InvalidModel("Offsets must be between -1 and 1.")
    if not 0 < fit.scale <= 2 or not -360 <= fit.rotation <= 360:
        raise InvalidModel("The placement settings are out of range.")
    values = {
        "asset_id": fit.asset_id,
        "rotation": fit.rotation,
        "scale": fit.scale,
        "offset_x": fit.offset_x,
        "offset_y": fit.offset_y,
        "offset_z": fit.offset_z,
    }
    with transaction.atomic():
        # Lock the asset so it cannot be deleted while this assignment is written.
        if not VisualModelAsset.objects.select_for_update().filter(pk=fit.asset_id).exists():
            raise InvalidModel("Select a model from the library.")
        assignment = (
            VisualModelAssignment.objects.select_for_update().filter(scope=scope, target_key=target_key).first()
        )
        if assignment is None:
            if expected_version != 0:
                raise ModelConflict
            try:
                with transaction.atomic():
                    return VisualModelAssignment.objects.create(scope=scope, target_key=target_key, **values)
            except IntegrityError as exc:
                # The unique target constraint rejected a concurrent create.
                raise ModelConflict from exc
        if assignment.version != expected_version:
            raise ModelConflict
        changed = False
        for field, value in values.items():
            if getattr(assignment, field) != value:
                setattr(assignment, field, value)
                changed = True
        if changed:
            assignment.version += 1
            assignment.save()
    return assignment


def unassign_model(scope: str, target_key: str, *, expected_version: int, actor) -> None:
    ensure_editor(actor)
    with transaction.atomic():
        assignment = (
            VisualModelAssignment.objects.select_for_update().filter(scope=scope, target_key=target_key).first()
        )
        if assignment is None:
            raise ModelNotFound
        if assignment.version != expected_version:
            raise ModelConflict
        assignment.delete()
