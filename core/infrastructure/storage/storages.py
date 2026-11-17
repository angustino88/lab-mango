"""
Custom django-storages backends for MinIO.

Each class reads MINIO_* Django settings directly so no AWS_* variables
are required anywhere in the codebase or .env files.
"""

from __future__ import annotations

from typing import Protocol, cast

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class _MinIOSettings(Protocol):
    """Settings supplied by local/production configuration when MinIO is enabled."""

    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str
    MINIO_ENDPOINT: str
    MINIO_REGION: str
    MINIO_USE_SSL: bool
    MINIO_SIGNATURE_VERSION: str
    MINIO_DEFAULT_ACL: str | None
    MINIO_QUERYSTRING_AUTH: bool
    MINIO_FILE_OVERWRITE: bool


def _base_minio_kwargs() -> dict[str, object]:
    """Build S3Boto3Storage constructor kwargs from MINIO_* Django settings."""
    minio = cast(_MinIOSettings, settings)
    return {
        "access_key": minio.MINIO_ACCESS_KEY,
        "secret_key": minio.MINIO_SECRET_KEY,
        "bucket_name": minio.MINIO_BUCKET,
        "endpoint_url": minio.MINIO_ENDPOINT,
        "region_name": minio.MINIO_REGION,
        "use_ssl": minio.MINIO_USE_SSL,
        "signature_version": minio.MINIO_SIGNATURE_VERSION,
        "default_acl": minio.MINIO_DEFAULT_ACL,
        "querystring_auth": minio.MINIO_QUERYSTRING_AUTH,
        "file_overwrite": minio.MINIO_FILE_OVERWRITE,
        "verify": minio.MINIO_USE_SSL,
        "addressing_style": "path",  # MinIO requires path-style: endpoint/bucket/key
    }


class MinIOStorage(S3Boto3Storage):
    """Base MinIO storage — reads MINIO_* settings, no AWS_* env vars needed."""

    def __init__(self, **kwargs):
        params = _base_minio_kwargs()
        params.update(kwargs)
        super().__init__(**params)


class StaticS3Storage(MinIOStorage):
    """Static files storage — served from the 'static/' prefix."""

    def __init__(self, **kwargs):
        kwargs.setdefault("location", "static")
        kwargs.setdefault("default_acl", "public-read")
        super().__init__(**kwargs)


class MediaS3Storage(MinIOStorage):
    """Media files storage — served from the 'media/' prefix."""

    def __init__(self, **kwargs):
        kwargs.setdefault("location", "media")
        kwargs.setdefault("file_overwrite", False)
        super().__init__(**kwargs)
