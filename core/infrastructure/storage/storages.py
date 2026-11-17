"""
Custom django-storages backends for MinIO.

Each class reads MINIO_* Django settings directly so no AWS_* variables
are required anywhere in the codebase or .env files.
"""
from __future__ import annotations

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


def _base_minio_kwargs() -> dict:
    """Build S3Boto3Storage constructor kwargs from MINIO_* Django settings."""
    return {
        "access_key": settings.MINIO_ACCESS_KEY,
        "secret_key": settings.MINIO_SECRET_KEY,
        "bucket_name": settings.MINIO_BUCKET,
        "endpoint_url": settings.MINIO_ENDPOINT,
        "region_name": settings.MINIO_REGION,
        "use_ssl": settings.MINIO_USE_SSL,
        "signature_version": settings.MINIO_SIGNATURE_VERSION,
        "default_acl": settings.MINIO_DEFAULT_ACL,
        "querystring_auth": settings.MINIO_QUERYSTRING_AUTH,
        "file_overwrite": settings.MINIO_FILE_OVERWRITE,
        "verify": settings.MINIO_USE_SSL,
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
