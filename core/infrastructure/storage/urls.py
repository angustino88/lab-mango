from __future__ import annotations

from django.conf import settings

from core.infrastructure.storage.client import generate_presigned_url


def get_media_url(file_field, request=None, base_url: str = "") -> str | None:
    """
    Centralized URL resolver for uploaded media files.

    Returns a presigned MinIO URL when MinIO is enabled, otherwise returns an
    absolute local URL if a request is available, or the storage-relative URL.
    """
    if not file_field:
        return None

    if getattr(settings, "MINIO_ENABLED", False):
        object_key = getattr(file_field, "name", None)
        if not object_key:
            return None

        storage = getattr(file_field, "storage", None)
        location = getattr(storage, "location", "media")
        if location:
            object_key = f"{location.rstrip('/')}/{object_key.lstrip('/')}"

        return generate_presigned_url(object_key)

    url = getattr(file_field, "url", None)
    if not url:
        return None
    if request:
        return request.build_absolute_uri(url)
    if base_url:
        return base_url.rstrip("/") + url
    return url
