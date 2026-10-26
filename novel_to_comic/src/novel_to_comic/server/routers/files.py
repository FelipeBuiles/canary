"""Read-only serving of project asset files to the web app.

Every station renders images the pipeline wrote into the project directory —
style proofs, character and location references, plates, the cover, page
renders — plus the ``.meta.json``/``.failure.json`` sidecars that explain how
each image was generated. The web app addresses all of them by relative path,
so this stays one generic reader rather than a bespoke route per asset kind.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import get_project
from ..file_cache import private_file_response

router = APIRouter()

# Project directories also hold pipeline configuration, and ``config.yaml``
# carries a gateway key field. No UI surface reads either, so they are not
# reachable through the asset path.
_DENIED_NAMES = frozenset({"config.yaml"})


def _is_denied(relative_path: Path) -> bool:
    return any(
        part.startswith(".") or part in _DENIED_NAMES
        for part in relative_path.parts
    )


def _project_file(project_dir: Path, file_path: str) -> tuple[Path, Path]:
    root = project_dir.resolve()
    full = (root / file_path).resolve()

    # Path traversal guard — is_relative_to, not a string prefix check, so a
    # sibling dir like "demo-private" can't slip past the guard for "demo".
    if not full.is_relative_to(root) or _is_denied(full.relative_to(root)):
        raise HTTPException(403, "Access denied")
    if not full.is_file():
        raise HTTPException(404, "File not found")
    return root, full


@router.get("/files/{file_path:path}")
def serve_project_file(file_path: str, request: Request, project=Depends(get_project)):
    """Serve one file from the authenticated user's project directory."""
    project_dir, _config, _state = project
    _root, full = _project_file(project_dir, file_path)

    media_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    # The UI changes an asset's query token whenever the asset changes, and
    # reuses the same URL otherwise. Revalidating keeps unchanged files to a
    # 304 across reloads, without making authenticated files publicly cacheable.
    return private_file_response(request, full, media_type)


@router.get("/thumbnails/{rendition}/{file_path:path}")
def serve_project_thumbnail(
    rendition: Literal["thumbnail", "card"], file_path: str, request: Request,
    project=Depends(get_project),
):
    """Serve a small WebP of one project image; the master stays at ``/files/``."""
    from novel_to_comic.asset_thumbnails import THUMBNAIL_SOURCE_SUFFIXES, ensure_asset_thumbnail

    project_dir, _config, _state = project
    root, full = _project_file(project_dir, file_path)
    if full.suffix.lower() not in THUMBNAIL_SOURCE_SUFFIXES:
        raise HTTPException(404, "File not found")
    try:
        thumbnail = ensure_asset_thumbnail(root, full, rendition)
    except FileNotFoundError:
        raise HTTPException(404, "File not found") from None
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Thumbnail could not be created") from exc
    return private_file_response(request, thumbnail, "image/webp")
