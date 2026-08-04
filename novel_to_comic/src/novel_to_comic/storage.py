"""Cloudflare R2 upload helper for user-facing exports (PDFs, CBZs).

R2 is optional — if the required env vars are not set, `r2_configured()`
returns False and callers should fall back to serving files from disk.
"""

import os
from hashlib import sha256
from pathlib import PurePath

import boto3

_R2_VARS = ("R2_ENDPOINT", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET", "R2_PUBLIC_URL")


def r2_configured() -> bool:
    return all(os.environ.get(v) for v in _R2_VARS)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )


def _export_key(user_id: str, project_name: str, filename: str, data: bytes) -> str:
    """Build an immutable content-addressed key for one finalized export."""

    safe_name = PurePath(filename).name
    if safe_name != filename:
        raise ValueError("export filename must not contain a path")
    return f"{user_id}/{project_name}/exports/{sha256(data).hexdigest()}/{safe_name}"


def export_url(user_id: str, project_name: str, filename: str, data: bytes) -> str:
    """Return the cache-safe public R2 URL for these exact export bytes."""

    key = _export_key(user_id, project_name, filename, data)
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"


def upload_export(user_id: str, project_name: str, filename: str, data: bytes) -> str:
    """Upload one immutable export to R2 with CDN-friendly response metadata."""

    key = _export_key(user_id, project_name, filename, data)
    media_type = "application/pdf" if filename.endswith(".pdf") else "application/zip"
    _client().put_object(
        Bucket=os.environ["R2_BUCKET"],
        Key=key,
        Body=data,
        ContentType=media_type,
        CacheControl="public, max-age=31536000, immutable",
        ContentDisposition=f'attachment; filename="{filename}"',
    )
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"
