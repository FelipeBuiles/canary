"""Authenticated, provider-free Pages lettering APIs."""

from __future__ import annotations

from functools import wraps
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from novel_to_comic.artifact_lock import production_lock
from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.lettering import LetteringStyle, PageLettering
from novel_to_comic.lettering.service import (
    LetteringConflict,
    composite_page,
    editor_state,
    ensure_style,
    is_hybrid,
    preset_style,
    reset_lettering,
    save_lettering,
    save_style,
)
from novel_to_comic.target_artifacts import (
    ArtifactInvalid,
    ArtifactMissing,
    TargetArtifacts,
)
from ..deps import get_project

router = APIRouter()


def _errors(fn):
    @wraps(fn)
    def invoke(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (LetteringConflict, ArtifactInvalid) as exc:
            raise HTTPException(409, str(exc)) from exc
        except ArtifactMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return invoke


class LetteringSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    expected_image_sha256: str = Field(min_length=64, max_length=64)
    expected_style_sha256: str = Field(min_length=64, max_length=64)
    state: PageLettering
    mark_reviewed: bool = False


class LetteringReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    expected_image_sha256: str = Field(min_length=64, max_length=64)


class StyleSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    style: LetteringStyle


@router.get("/pages/{page_number}/lettering")
@_errors
def get_lettering(page_number: int, project=Depends(get_project)):
    return editor_state(TargetArtifacts(project[0]), page_number)


@router.put("/pages/{page_number}/lettering")
@_errors
def put_lettering(page_number: int, body: LetteringSave, project=Depends(get_project)):
    target = TargetArtifacts(project[0])
    save_lettering(
        target, page_number, body.state, **body.model_dump(exclude={"state"})
    )
    return editor_state(target, page_number)


@router.post("/pages/{page_number}/lettering/reset")
@_errors
def reset_page_lettering(
    page_number: int, body: LetteringReset, project=Depends(get_project)
):
    target = TargetArtifacts(project[0])
    reset_lettering(target, page_number, **body.model_dump())
    return editor_state(target, page_number)


@router.get("/lettering/style")
@_errors
def get_lettering_style(project=Depends(get_project)):
    target = TargetArtifacts(project[0])
    if not is_hybrid(target):
        raise LetteringConflict(
            "Editable lettering is available for new hybrid editions only."
        )
    return {
        "style": ensure_style(target),
        "presets": {
            name: preset_style(name)
            for name in ("literary", "classic", "pulp", "minimal")
        },
    }


@router.put("/lettering/style")
@_errors
def put_lettering_style(body: StyleSave, project=Depends(get_project)):
    target = TargetArtifacts(project[0])
    if not is_hybrid(target):
        raise LetteringConflict(
            "This edition has baked lettering; its style is not editable."
        )
    return save_style(target, body.style, expected_revision=body.expected_revision)


@router.get("/pages/{page_number}/composite/{rendition}")
@_errors
def get_page_composite(
    page_number: int,
    rendition: Literal["full", "reader", "thumbnail"],
    render_revision: int | None = None,
    project=Depends(get_project),
):
    # Capture bytes under the artifact lock. A simultaneous save may unlink a
    # derived file immediately after this response; it must not break its stream.
    with production_lock(project[0]):
        path, identity = composite_page(
            TargetArtifacts(project[0]),
            page_number,
            rendition=rendition,
            expected_render_revision=render_revision,
        )
        data = path.read_bytes()
    return Response(
        data,
        media_type="image/png" if rendition == "full" else "image/webp",
        headers={
            "Cache-Control": "private, no-cache",
            **({"ETag": f'"{identity}-{rendition}"'} if identity else {}),
        },
    )
