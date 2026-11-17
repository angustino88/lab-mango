from __future__ import annotations

import posixpath
import uuid
from pathlib import PurePath
from typing import Protocol

from django.utils import timezone
from django.utils.deconstruct import deconstructible
from django.utils.text import slugify

DEFAULT_RESOURCE_FOLDER = "resources"
DEFAULT_CATEGORY = "uncategorized"
DEFAULT_EXTENSION = ".jpg"
DEFAULT_IDENTIFIER = "resource"
DEFAULT_USERNAME = "unknown"


class _UserLike(Protocol):
    username: str | None


class _ResourceLike(Protocol):
    sku: object | None
    kind: object | None
    creator: _UserLike | None
    last_modified_by: _UserLike | None


def _safe_component(value: object | None, fallback: str) -> str:
    if value is None:
        return fallback
    return slugify(str(value), allow_unicode=False) or fallback


def _normalize_relative_folder(folder: str) -> str:
    normalized = folder.strip().replace("\\", "/").strip("/")
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Resource upload folder must be a non-empty relative path.")
    return posixpath.join(*parts)


@deconstructible
class ResourceImageUploadPath:
    """Create unique and storage-safe image paths for resource models."""

    def __call__(self, resource: _ResourceLike, original_filename: str) -> str:
        return posixpath.join(
            self._resource_folder(resource),
            self._build_filename(resource, original_filename),
        )

    def _resource_folder(self, resource: _ResourceLike) -> str:
        configured_folder = getattr(resource, "image_upload_folder", None)
        if configured_folder is None:
            configured_folder = getattr(resource, "IMAGE_UPLOAD_FOLDER", None)
        if configured_folder is not None:
            equipment_folder = _normalize_relative_folder(configured_folder)
            return posixpath.join(DEFAULT_RESOURCE_FOLDER, equipment_folder)
        model_name = type(resource).__name__
        category_name = model_name.removesuffix("Equipment")
        category = _safe_component(category_name, DEFAULT_CATEGORY)
        return posixpath.join(DEFAULT_RESOURCE_FOLDER, category)

    def _build_filename(self, resource: _ResourceLike, original_filename: str) -> str:
        username = self._username(resource)
        identifier = _safe_component(
            getattr(resource, "sku", None)
            or getattr(resource, "pk", None)
            or getattr(resource, "id", None),
            DEFAULT_IDENTIFIER,
        )
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
        unique_id = uuid.uuid4().hex
        extension = self._extension(original_filename)
        return f"{username}_{identifier}_{timestamp}_{unique_id}{extension}"

    @staticmethod
    def _username(resource: _ResourceLike) -> str:
        user = getattr(resource, "last_modified_by", None) or getattr(
            resource, "creator", None
        )
        return _safe_component(getattr(user, "username", None), DEFAULT_USERNAME)

    @staticmethod
    def _extension(original_filename: str) -> str:
        extension = PurePath(original_filename).suffix.lower()
        if not extension or not extension[1:].isalnum():
            return DEFAULT_EXTENSION
        return extension

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@deconstructible
class FolderUploadPath:
    def __init__(self, folder: str):
        self.folder = _normalize_relative_folder(folder)

    def __call__(self, instance: object, filename: str) -> str:
        return posixpath.join(self.folder, filename)

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.folder == other.folder

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.folder!r})"

