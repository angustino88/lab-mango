"""
File upload/delete services.

- UploadLocalService  — local filesystem (MEDIA_ROOT), used when MinIO is off
- UploadMinIOService  — MinIO object storage, used when USE_MINIO=True
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import InMemoryUploadedFile

logger = logging.getLogger(__name__)


class UploadLocalService:
    """
    Thin wrapper around Django's FileSystemStorage for saving/deleting
    files under a given sub-path of MEDIA_ROOT.

    Usage:
        svc = UploadLocalService(data=file_obj, file_name="photo.jpg", location="avatars")
        url = svc.upload_local()    # returns media URL string
        svc.delete_local()          # deletes the file saved by upload_local()
    """

    def __init__(self, data: InMemoryUploadedFile, file_name: str, location: str) -> None:
        self.data = data
        self.file_name = file_name
        self.location = location
        self._fs = FileSystemStorage(
            location=str(Path(settings.MEDIA_ROOT) / location),
            base_url=f"{settings.MEDIA_URL}{location}",
        )
        self._saved_name: str | None = None

    def upload_local(self) -> str:
        """Save file and return its media URL."""
        self._saved_name = self._fs.save(self.file_name, self.data)
        return self._fs.url(self._saved_name)

    def delete_local(self) -> bool:
        """Delete the file saved by `upload_local()`. Returns True on success, False on failure."""
        name_to_delete = self._saved_name or self.file_name
        try:
            self._fs.delete(name_to_delete)
            return True
        except Exception as exc:
            logger.warning("UploadLocalService.delete_local failed: %s", exc)
            return False


class UploadMinIOService:
    """
    Upload/delete files in MinIO via the configured django-storages backend.

    Returns a presigned URL so the frontend can access the file directly
    without routing through Django.

    Usage:
        svc = UploadMinIOService(data=file_obj, file_name="photo.jpg", location="avatars")
        url = svc.upload_to_minio()   # presigned URL string or None
        svc.delete_from_minio()       # True / False
    """

    def __init__(self, data: InMemoryUploadedFile, file_name: str, location: str) -> None:
        self.data = data
        self.file_name = file_name
        self.location = location
        self._object_key: str | None = None

    def upload_to_minio(self) -> str | None:
        """Upload file to MinIO and return a presigned GET URL."""
        from core.infrastructure.storage.client import generate_presigned_url
        from core.infrastructure.storage.storages import MediaS3Storage

        storage = MediaS3Storage()
        path = f"{self.location}/{self.file_name}"
        self._object_key = storage.save(path, self.data)
        return generate_presigned_url(self._object_key)

    def delete_from_minio(self) -> bool:
        """Delete file from MinIO. Returns True on success."""
        from core.infrastructure.storage.storages import MediaS3Storage

        key = self._object_key or f"{self.location}/{self.file_name}"
        try:
            MediaS3Storage().delete(key)
            return True
        except Exception as exc:
            logger.warning("UploadMinIOService.delete_from_minio failed: %s", exc)
            return False
