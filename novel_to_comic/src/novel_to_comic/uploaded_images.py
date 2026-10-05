"""Validation for author-uploaded reference images (Style directions, Cast attachments)."""
from __future__ import annotations

import io
import warnings

IMAGE_SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 40_000_000
_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP"}


class UploadedImageError(ValueError):
    """The upload is not an accepted image; the message is author-facing."""


def image_suffix(content_type: str | None) -> str:
    suffix = IMAGE_SUFFIXES.get((content_type or "").lower(), "")
    if not suffix:
        raise UploadedImageError("must be PNG, JPEG, or WebP")
    return suffix


def decode_uploaded_image(image_bytes: bytes, suffix: str) -> tuple[int, int]:
    """Return (width, height) after checking format, bounds, and integrity."""
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as decoded:
                if decoded.format != _FORMATS[suffix]:
                    raise ValueError("declared and decoded image formats differ")
                if (
                    decoded.width > MAX_IMAGE_DIMENSION
                    or decoded.height > MAX_IMAGE_DIMENSION
                    or decoded.width * decoded.height > MAX_IMAGE_PIXELS
                ):
                    raise ValueError("decoded image dimensions exceed limits")
                size = decoded.size
                decoded.verify()
    except Exception:
        raise UploadedImageError("is not a valid image") from None
    return size
