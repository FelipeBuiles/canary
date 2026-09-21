"""Authenticated Pages lettering APIs and explicit credited project translation."""

from __future__ import annotations

from functools import wraps
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from novel_to_comic.artifact_lock import production_lock
from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.lettering import LetteringStyle, PageLettering
from novel_to_comic.lettering.service import (
    LetteringConflict,
    composite_page,
    editor_state,
    ensure_style,
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
from ..deps import get_project, project_key
from ..auth import get_current_user
from ..credited_job import enqueue_reserved_generation_job
from ..generation_jobs import generation_job_payload
from novel_to_comic.lettering.translation import (
    TargetLocale, TranslationSnapshotConflict, assert_snapshot,
    prepare_translation, translate_project,
)

router = APIRouter()


def _errors(fn):
    @wraps(fn)
    def invoke(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except TranslationSnapshotConflict as exc:
            raise HTTPException(412, str(exc)) from exc
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


def _require_editable_style(target: TargetArtifacts) -> None:
    from novel_to_comic.config import load_config

    try:
        edition = target.read_book_edition()
    except ArtifactMissing:
        if load_config(target.project_dir)[0].lettering_mode == "integrated":
            raise LetteringConflict("This project uses integrated lettering. Text is drawn with the artwork.")
        return  # Before Draw: defining a book style is provider-free.
    if edition.capability_profile.exact_visible_lettering:
        raise LetteringConflict("This edition has baked lettering; its style is not editable.")


@router.get("/lettering/style")
@_errors
def get_lettering_style(project=Depends(get_project)):
    target = TargetArtifacts(project[0])
    _require_editable_style(target)
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
    _require_editable_style(target)
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
            draft_preview=True,
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


class LetteringTranslate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_locale: TargetLocale
    expected_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/lettering/translation-estimate")
@_errors
def get_translation_estimate(target_locale: TargetLocale, project=Depends(get_project)):
    return prepare_translation(TargetArtifacts(project[0]), project[1], target_locale).estimate


@router.post("/lettering/translate")
async def post_translation(
    project_id: str, body: LetteringTranslate, request: Request,
    project=Depends(get_project), user_id: str = Depends(get_current_user),
):
    target = TargetArtifacts(project[0])
    try:
        with production_lock(project[0]):
            prepared = prepare_translation(target, project[1], body.target_locale)
            assert_snapshot(prepared, body.expected_snapshot_sha256)

            async def work():
                await translate_project(target, project[1], prepared)

            from ..job_commands import command, snapshot
            job, _ = enqueue_reserved_generation_job(
                request.app, project_name=project_key(user_id, project_id),
                user_id=user_id, project_id=project_id, project_dir=project[0],
                stage="lettering", kind="lettering_translation", label=f"Translate lettering to {body.target_locale}",
                payload=body.model_dump(), work=work, debit_description="Project lettering translation",
                command=command("lettering_translation", project[0], project[1], prepared=snapshot(prepared)),
                reservation_credits=prepared.estimate["reserved_credits"],
                operations=(("text", prepared.model),),
            )
    except TranslationSnapshotConflict as exc:
        raise HTTPException(412, str(exc)) from exc
    except (LetteringConflict, ArtifactInvalid) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"job": generation_job_payload(request.app, job)}
