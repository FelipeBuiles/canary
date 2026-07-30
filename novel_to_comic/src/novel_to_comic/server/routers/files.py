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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..deps import get_project

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


@router.get("/files/{file_path:path}")
def serve_project_file(file_path: str, project=Depends(get_project)):
    """Serve one file from the authenticated user's project directory."""
    project_dir, _config, _state = project
    root = project_dir.resolve()
    full = (root / file_path).resolve()

    # Path traversal guard — is_relative_to, not a string prefix check, so a
    # sibling dir like "demo-private" can't slip past the guard for "demo".
    if not full.is_relative_to(root) or _is_denied(full.relative_to(root)):
        raise HTTPException(403, "Access denied")
    if not full.is_file():
        raise HTTPException(404, "File not found")

    media_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    return FileResponse(
        full,
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )
