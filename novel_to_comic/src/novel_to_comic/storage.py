"""Cloudflare R2 upload helper for user-facing exports (PDFs, CBZs).

R2 is optional — if the required env vars are not set, `r2_configured()`
returns False and callers should fall back to serving files from disk.
"""

import os

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


def export_url(user_id: str, project_name: str, filename: str) -> str:
    """Return the public R2 URL for an export file without uploading."""
    key = f"{user_id}/{project_name}/exports/{filename}"
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"


def upload_export(user_id: str, project_name: str, filename: str, data: bytes) -> str:
    """Upload an export file to R2 and return its public URL."""
    key = f"{user_id}/{project_name}/exports/{filename}"
    _client().put_object(Bucket=os.environ["R2_BUCKET"], Key=key, Body=data)
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"
