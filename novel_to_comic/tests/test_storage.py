from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

from novel_to_comic import storage


def test_r2_exports_are_content_addressed_and_cacheable(monkeypatch):
    client = MagicMock()
    payload = b"comic export bytes"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(storage, "_client", lambda: client)
    monkeypatch.setenv("R2_BUCKET", "scenewright-media")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://media.scenewright.ink")

    url = storage.upload_export("author-1", "book-1", "comic.pdf", payload)

    assert url == f"https://media.scenewright.ink/author-1/book-1/exports/{digest}/comic.pdf"
    client.put_object.assert_called_once_with(
        Bucket="scenewright-media",
        Key=f"author-1/book-1/exports/{digest}/comic.pdf",
        Body=payload,
        ContentType="application/pdf",
        CacheControl="public, max-age=31536000, immutable",
        ContentDisposition='attachment; filename="comic.pdf"',
    )
