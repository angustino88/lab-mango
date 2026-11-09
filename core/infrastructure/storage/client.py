"""
MinIO / S3 low-level helpers.

Provides a pre-configured boto3 client and presigned URL generation
for objects stored in MinIO, using settings from Django config.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_setting(*names: str, default=None):
    """Return the first non-empty value found in Django settings."""
    for name in names:
        val = getattr(settings, name, None)
        if val not in (None, ""):
            return val
    return default


def get_minio_client():
    """Create a boto3 S3 client configured for MinIO (path-style addressing)."""
    endpoint = _get_setting("MINIO_ENDPOINT", "AWS_S3_ENDPOINT_URL")
    access_key = _get_setting("MINIO_ACCESS_KEY", "AWS_ACCESS_KEY_ID")
    secret_key = _get_setting("MINIO_SECRET_KEY", "AWS_SECRET_ACCESS_KEY")
    signature_version = _get_setting(
        "MINIO_SIGNATURE_VERSION", "AWS_S3_SIGNATURE_VERSION", default="s3v4"
    )
    use_ssl = _get_setting("MINIO_USE_SSL", "AWS_S3_USE_SSL", default=False)
    raw_verify = _get_setting("AWS_S3_VERIFY")
    if raw_verify is None:
        verify = bool(use_ssl)
    elif isinstance(raw_verify, bool):
        verify = raw_verify
    else:
        verify = str(raw_verify).strip().lower() not in ("false", "0", "no")


    config = Config(
        signature_version=signature_version,
        s3={"addressing_style": "path"},
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=config,
        verify=verify,
    )


def generate_presigned_url(object_key: str, expires_in: int = 604800) -> str | None:
    """
    Generate a presigned GET URL for a MinIO object.

    Args:
        object_key: Path of the object inside the bucket.
        expires_in: Expiry in seconds. Default is 7 days.

    Returns:
        Presigned URL string, or None on failure.
    """
    try:
        client = get_minio_client()
        bucket = _get_setting("MINIO_BUCKET", "AWS_STORAGE_BUCKET_NAME")
        if not bucket:
            logger.error("generate_presigned_url: no storage bucket configured")
            return None
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        logger.error("Error generating presigned URL for %s: %s", object_key, exc)
        return None


def extract_object_key_from_url(url: str | None) -> str | None:
    """
    Strip the endpoint + bucket prefix from a MinIO URL to obtain the object key.

    Example:
        "http://minio:9000/my-bucket/avatars/photo.jpg" → "avatars/photo.jpg"
    """
    if not url:
        return None

    parsed = urlparse(url)
    path = parsed.path.lstrip("/")

    bucket = _get_setting("MINIO_BUCKET", "AWS_STORAGE_BUCKET_NAME")
    if bucket and path.startswith(f"{bucket}/"):
        return path[len(bucket) + 1 :]

    return path
