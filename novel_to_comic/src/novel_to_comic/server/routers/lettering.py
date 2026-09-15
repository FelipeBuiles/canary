"""Authenticated, provider-free Pages lettering edits and final previews."""

from __future__ import annotations

import io
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from novel_to_comic.lettering_service import (
    hybrid_edition,
    load_lettering,
    page_aspect,
    prepare_lettering,
    response_payload,
    save_lettering,
    saved_composite,
)
from novel_to_comic.models.lettering import PageLettering, LetteringStyle
from novel_to_comic.page_lettering import resolve_lettering, style_preset
from novel_to_comic.target_artifacts import (
    ArtifactMissing,
    ArtifactInvalid,
    TargetArtifacts,
)
from ..deps import get_project
from ..ratelimit import limiter

router = APIRouter()


class LetteringWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: PageLettering
    expected_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class ResetRequest(BaseModel):
    expected_sha256: str | None = None


class BookStyleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: LetteringStyle
    # Every current page is explicitly version-bound, preventing unseen overwrites.
    expected_pages: dict[int, str | None]


def _error(exc):
    return HTTPException(409, str(exc))


@router.get("/lettering/presets")
def presets(project=Depends(get_project)):
    return {key: style_preset(key) for key in ("literary", "noir", "manga", "vintage")}


@router.get("/pages/{page_number}/lettering")
def get_lettering(page_number: int, project=Depends(get_project)):
    artifacts = TargetArtifacts(project[0])
    try:
        with artifacts.lettering_lock():
            if not hybrid_edition(artifacts):
                return {
                    "mode": "baked",
                    "message": "Text is part of this retained artwork. Create a new Draw edition for editable lettering.",
                }
            aspect, revision = page_aspect(artifacts, page_number)
            state = load_lettering(artifacts, page_number, aspect)
            state = resolve_lettering(state, artifacts.read_page(page_number), aspect)
            return response_payload(artifacts, state, aspect, revision)
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/pages/{page_number}/lettering/preview")
@limiter.limit("120/minute")
def preview_lettering(
    request: Request,
    page_number: int,
    body: LetteringWrite,
    project=Depends(get_project),
):
    artifacts = TargetArtifacts(project[0])
    if body.state.page_number != page_number:
        raise HTTPException(422, "Page route and lettering state must match")
    try:
        with artifacts.lettering_lock():
            state, aspect, revision = prepare_lettering(artifacts, body.state)
            return response_payload(artifacts, state, aspect, revision)
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _error(exc) from exc


@router.put("/pages/{page_number}/lettering")
def put_lettering(page_number: int, body: LetteringWrite, project=Depends(get_project)):
    artifacts = TargetArtifacts(project[0])
    if body.state.page_number != page_number:
        raise HTTPException(422, "Page route and lettering state must match")
    try:
        with artifacts.lettering_lock():
            return save_lettering(
                artifacts, body.state, expected_sha256=body.expected_sha256
            )
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/pages/{page_number}/lettering/reset")
def reset_lettering(page_number: int, body: ResetRequest, project=Depends(get_project)):
    artifacts = TargetArtifacts(project[0])
    try:
        with artifacts.lettering_lock():
            aspect, _ = page_aspect(artifacts, page_number)
            fresh = load_lettering(artifacts, page_number, aspect, reseed=True)
            return save_lettering(
                artifacts, fresh, expected_sha256=body.expected_sha256
            )
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _error(exc) from exc


@router.put("/lettering/style")
def put_book_style(body: BookStyleWrite, project=Depends(get_project)):
    """Explicit book-wide operation; validate the entire batch before writing."""
    artifacts = TargetArtifacts(project[0])
    try:
        with artifacts.lettering_lock():
            if not hybrid_edition(artifacts):
                raise ValueError(
                    "Baked editions cannot receive post-production lettering"
                )
            pages = [
                ref.page_number
                for ref in artifacts.read_plan().pages
                if artifacts.provenance_revisions(ref.page_number)
            ]
            if set(body.expected_pages) != set(pages):
                raise ValueError(
                    "Book pages changed. Refresh before applying a book-wide style."
                )
            prepared = []
            for number in pages:
                aspect, _ = page_aspect(artifacts, number)
                old = (
                    artifacts.read_lettering(number)
                    if artifacts.lettering_path(number).exists()
                    else None
                )
                if (old.content_sha256 if old else None) != body.expected_pages[number]:
                    raise ValueError(
                        f"Page {number} changed in another session. No book styles were applied."
                    )
                state = load_lettering(artifacts, number, aspect)
                state = PageLettering(
                    **(
                        state.model_dump(exclude={"content_sha256"})
                        | {
                            "style": body.style,
                            "reviewed_against_render_revision": None,
                        }
                    )
                )
                prepared.append(prepare_lettering(artifacts, state)[0])
            for state in prepared:
                save_lettering(
                    artifacts,
                    state,
                    expected_sha256=body.expected_pages[state.page_number],
                )
            artifacts.write_lettering_style(body.style)
            return {"updated_pages": pages}
    except (ArtifactMissing, ArtifactInvalid, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/pages/{page_number}/composite/{render_revision}/{rendition}")
def composite_preview(
    page_number: int, render_revision: int, rendition: str, project=Depends(get_project)
):
    if rendition not in {"reader", "thumbnail"}:
        raise HTTPException(404, "Unknown rendition")
    artifacts = TargetArtifacts(project[0])
    try:
        with artifacts.lettering_lock():
            image = artifacts.read_render(page_number, render_revision)
            if hybrid_edition(artifacts):
                # Never overlay current placement onto an unrelated historical render.
                if render_revision != artifacts.provenance_revisions(page_number)[-1]:
                    raise ValueError(
                        "Open historical art in artwork review; final preview uses the active render"
                    )
                image, _state, _identity = saved_composite(
                    artifacts, page_number, image
                )
            with Image.open(io.BytesIO(image)) as original:
                original.thumbnail(
                    (424 if rendition == "thumbnail" else 1024, 8192),
                    Image.Resampling.LANCZOS,
                )
                output = io.BytesIO()
                original.convert("RGB").save(output, "WEBP", quality=85)
            return Response(
                output.getvalue(),
                media_type="image/webp",
                headers={"Cache-Control": "private, no-cache"},
            )
    except (ArtifactMissing, ArtifactInvalid, ValueError, OSError) as exc:
        raise _error(exc) from exc
