"""Per-asset regeneration and version history for the Cast station.

The Cast stage generates every character sheet, appearance state, location
plate, and prop reference in one run. These routes are the follow-up: an author
looking at one bad asset re-rolls it, edits it with an instruction, or restores
an earlier version — without re-running the stage.
"""

from __future__ import annotations


from pathlib import Path
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic import artifacts
from novel_to_comic.cast_reference_inputs import CastReferenceInput, store_reference_upload
from novel_to_comic.asset_versions import list_asset_versions, restore_asset_version
from novel_to_comic.cast_instructions import (
    MAX_INSTRUCTION_CHARS,
    resolve_cast_asset,
    restore_asset_instruction_direction,
)
from novel_to_comic.cast_target import ASSET_TYPES, AssetType, CastTarget

from ..auth import get_current_user
from ..credits import UnifiedCostResolver
from novel_to_comic.codex_dev import CodexRoutingError
from ..deps import get_project
from ..ratelimit import cost_limit, limiter

from ..cast_admission import quote_cast_regen, submit_cast_regen, submit_instructed_regen

router = APIRouter()


@router.get("/cast/review")
def cast_review(project_id: str, project=Depends(get_project),
                user_id: str = Depends(get_current_user)):
    from novel_to_comic.cast_design import review_status
    project_dir, config, _state = project
    return review_status(config, project_dir)


class DismissReviewNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_ids: list[str] = Field(default_factory=list, max_length=20)
    location_ids: list[str] = Field(default_factory=list, max_length=20)
    concern: str = Field(min_length=1, max_length=40)


@router.post("/cast/review/dismiss", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def dismiss_cast_review_note(body: DismissReviewNoteRequest, project=Depends(get_project),
                             user_id: str = Depends(get_current_user)):  # noqa: ARG001 — auth gate
    """The author judged one Character Check note fine for the current sheets."""
    from novel_to_comic.cast_design import dismiss_review_issue, review_status
    project_dir, config, _state = project
    try:
        dismiss_review_issue(config, project_dir, body.character_ids, body.concern, body.location_ids)
    except KeyError as exc:
        raise HTTPException(404, exc.args[0]) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return review_status(config, project_dir)


@router.get("/cast/freshness")
def cast_reference_freshness(project=Depends(get_project)):
    """Each reference: current, outdated (its entity was edited) or missing."""
    from novel_to_comic.stages.s3_cast import reference_freshness

    project_dir, config, _state = project
    return {"references": reference_freshness(config, project_dir)}


class KeepReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["characters", "locations", "props"]
    entity_id: str = Field(min_length=1)
    state_id: str | None = None


@router.post("/cast/references/keep", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def keep_cast_reference(body: KeepReferenceRequest, project=Depends(get_project)):
    """Keep an out-of-date reference as it is after its entity was edited."""
    from novel_to_comic.stages.s3_cast import keep_current_reference, reference_freshness

    project_dir, config, _state = project
    try:
        keep_current_reference(config, project_dir, body.kind, body.entity_id, body.state_id)
    except KeyError as exc:
        raise HTTPException(404, f"Not in the Story Bible: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"references": reference_freshness(config, project_dir)}


@router.post("/cast/reopen", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def reopen_cast(project=Depends(get_project)):
    """Reopen an approved Cast so it regenerates out-of-date or missing references.

    Nothing is deleted: Cast redesigns only edited characters and regenerates
    only references that are not current, then returns to its checkpoint.
    """
    from novel_to_comic.series import reopen_cast
    from novel_to_comic.stages.s3_cast import reference_freshness

    project_dir, config, _state = project
    pending = [item for item in reference_freshness(config, project_dir) if item["status"] != "current"]
    if not pending:
        raise HTTPException(409, "Every Cast reference is current.")
    if not reopen_cast(project_dir):
        raise HTTPException(409, "Cast is not approved yet; resume it from Cast.")
    return {"reopened": True, "references": pending}


@router.post("/cast/reference-uploads", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
async def upload_cast_reference(image: UploadFile = File(...), project=Depends(get_project)):
    """Store an author's image so a Cast correction can attach it. No spend."""
    from novel_to_comic.uploaded_images import (
        MAX_IMAGE_BYTES, UploadedImageError, decode_uploaded_image, image_suffix,
    )

    project_dir, _config, _state = project
    try:
        suffix = image_suffix(image.content_type)
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Reference images must be 10 MB or smaller.")
        decode_uploaded_image(data, suffix)
    except UploadedImageError as exc:
        raise HTTPException(400, f"Reference image {exc}.") from None
    def keep():
        from ..storage_budget import ingestion
        with ingestion(project_dir, len(data) + 4096):
            return store_reference_upload(project_dir, data, suffix, image.filename)
    return await asyncio.to_thread(keep)


@router.get("/cast/reference-uploads/{upload_id}")
def get_cast_reference_upload(upload_id: str, project=Depends(get_project)):
    """Serve an uploaded attachment by id, so restored drafts can show it."""
    from fastapi.responses import FileResponse
    from novel_to_comic.cast_reference_inputs import UploadedReference, upload_descriptor
    from novel_to_comic.workspace import series_root

    project_dir, _config, _state = project
    try:
        UploadedReference(upload_id=upload_id)
    except ValueError:
        raise HTTPException(404, "Reference image not found") from None
    try:
        descriptor = upload_descriptor(project_dir, upload_id)
    except HTTPException:
        raise HTTPException(404, "Reference image not found") from None
    return FileResponse(series_root(project_dir) / descriptor["image_path"],
                        headers={"Cache-Control": "private, max-age=3600"})


class CastInstructionRequest(BaseModel):
    # Reject mismatched request fields instead of silently dropping attachments
    # and charging for a correction that cannot honor the author's request.
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=MAX_INSTRUCTION_CHARS)
    reference_assets: list[CastReferenceInput] | None = Field(default=None, max_length=3)


class InstructedRefRegenRequest(CastInstructionRequest):
    char_id: str = Field(min_length=1)
    # Redraw the character's looks from the new sheet in the same job.
    with_looks: bool = False


class InstructedPlateRegenRequest(CastInstructionRequest):
    loc_id: str = Field(min_length=1)
    with_looks: bool = False


class InstructedPropRegenRequest(CastInstructionRequest):
    prop_id: str = Field(min_length=1)


class InstructedStateRegenRequest(CastInstructionRequest):
    pass


def _require_path_safe_id(value: str, field_name: str) -> str:
    """Reject ids that would escape the project directory.

    Deliberately looser than the generated-id charset: appearance-state ids come
    from the model ("silver", "after the fire"), so a charset test would reject
    assets that exist. What must never pass is a path separator.
    """
    if not value or value in {".", ".."} or any(c in value for c in "/\\\x00"):
        raise HTTPException(400, f"Invalid {field_name}")
    return value


def _require_cast_asset(project_dir, asset_type: str, asset_id: str, state_id=None):
    """404 for an id the Story Bible doesn't have, before anything is estimated.

    This is the real guard on the regen routes: an id that resolves to a Story
    Bible entry is by construction a real asset, which no charset test can tell
    you. The estimator also raises for an unknown state, which without this
    would surface a plain typo as a 500.
    """
    resolve_cast_asset(project_dir, asset_type, asset_id, state_id)


def _cast_target(
    asset_type: AssetType, entity_id: str, entity_field: str, state_id: str | None = None
) -> CastTarget:
    """The HTTP edge: ids that would escape the project never become a target."""
    _require_path_safe_id(entity_id, entity_field)
    if state_id is not None:
        _require_path_safe_id(state_id, "state_id")
    return CastTarget(asset_type, entity_id, state_id)


@router.get("/asset-regen-estimate")
async def asset_regen_estimate(
    project_id: str,
    asset_type: str = Query(...),
    asset_id: str = Query(...),
    state_id: str | None = Query(None),
    reference_count: int | None = Query(None, ge=0, le=3),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the estimated credit cost to regenerate one cast asset."""
    if asset_type not in ASSET_TYPES:
        raise HTTPException(
            400, f"Unknown asset_type: {asset_type}. Valid: {', '.join(ASSET_TYPES)}")
    _require_path_safe_id(asset_id, "asset_id")
    if state_id is not None and asset_type == "prop":
        raise HTTPException(400, "state_id is not supported for prop assets")
    target = _cast_target(asset_type, asset_id, "asset_id", state_id)

    project_dir, config, _state = project
    _require_cast_asset(project_dir, asset_type, asset_id, state_id)
    quote = quote_cast_regen(
        config, project_dir, target, reference_count=reference_count, with_looks=True)
    try:
        instruction_estimate = UnifiedCostResolver.estimate_instructed_regen_cost(
            config, quote.asset_estimate, "cast"
        )
    except CodexRoutingError as exc:
        instruction_estimate = {"supported": False, "error": str(exc)}
    looks = None
    if quote.looks:
        looks = {"count": len(quote.looks["look_ids"]), "estimate_credits": quote.looks["estimate_credits"]}
    return {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "state_id": state_id,
        "looks": looks,
        "reference_assets_supported": True,
        **quote.asset_estimate,
        "instruction_estimate": instruction_estimate,
    }


async def _regen(request, project, user_id, project_id, target, **kwargs):
    project_dir, config, _state = project
    return await submit_cast_regen(
        request.app, config, project_dir, user_id, project_id, target, **kwargs)


async def _regen_instructed(request, project, user_id, project_id, target, body, **kwargs):
    project_dir, config, _state = project
    return await submit_instructed_regen(
        request.app, config, project_dir, user_id, project_id, target,
        body.instruction, body.reference_assets, **kwargs)


@router.post("/regen-ref", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_ref(
    request: Request,
    project_id: str,
    char_id: str = Query(...),
    with_looks: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("character", char_id, "char_id")
    return await _regen(request, project, user_id, project_id, target, with_looks=with_looks)


@router.post("/regen-state-ref", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_state_ref(
    request: Request,
    project_id: str,
    char_id: str = Query(...),
    state_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("character", char_id, "char_id", state_id)
    return await _regen(request, project, user_id, project_id, target)


@router.post("/regen-plate", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_plate(
    request: Request,
    project_id: str,
    loc_id: str = Query(...),
    with_looks: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("location", loc_id, "loc_id")
    return await _regen(request, project, user_id, project_id, target, with_looks=with_looks)


@router.post("/locations/{loc_id}/states/{state_id}/regenerate", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regenerate_location_state(
    request: Request,
    project_id: str,
    loc_id: str,
    state_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("location", loc_id, "loc_id", state_id)
    return await _regen(request, project, user_id, project_id, target)


@router.post("/regen-prop", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_prop(
    request: Request,
    project_id: str,
    prop_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("prop", prop_id, "prop_id")
    return await _regen(request, project, user_id, project_id, target)


@router.post("/regen-ref-instructed", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_ref_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedRefRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("character", body.char_id, "char_id")
    return await _regen_instructed(
        request, project, user_id, project_id, target, body, with_looks=body.with_looks)


@router.post("/regen-plate-instructed", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_plate_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPlateRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("location", body.loc_id, "loc_id")
    return await _regen_instructed(
        request, project, user_id, project_id, target, body, with_looks=body.with_looks)


@router.post("/regen-prop-instructed", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regen_prop_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPropRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("prop", body.prop_id, "prop_id")
    return await _regen_instructed(request, project, user_id, project_id, target, body)


@router.post("/characters/{char_id}/states/{state_id}/regenerate-instructed", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regenerate_character_state_instructed(
    request: Request,
    project_id: str,
    char_id: str,
    state_id: str,
    body: InstructedStateRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("character", char_id, "char_id", state_id)
    return await _regen_instructed(request, project, user_id, project_id, target, body)


@router.post("/locations/{loc_id}/states/{state_id}/regenerate-instructed", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def regenerate_location_state_instructed(
    request: Request,
    project_id: str,
    loc_id: str,
    state_id: str,
    body: InstructedStateRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    target = _cast_target("location", loc_id, "loc_id", state_id)
    return await _regen_instructed(request, project, user_id, project_id, target, body)


def _character_ref_sheet_path(
    project_dir: Path, char_id: str, state_id: str | None
) -> Path:
    base = artifacts.character_ref_sheet_path(project_dir, char_id).parent
    return base / "states" / state_id / "sheet.png" if state_id else base / "sheet.png"


@router.get("/character-ref-versions")
def get_character_ref_versions(
    char_id: str = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    """Archived re-roll history for a character ref sheet (canonical or a state)."""
    project_dir, config, _state = project
    _require_path_safe_id(char_id, "char_id")
    if state_id is not None:
        _require_path_safe_id(state_id, "state_id")
    sheet = _character_ref_sheet_path(project_dir, char_id, state_id)
    versions = list_asset_versions(sheet, project_dir)
    return {
        "char_id": char_id,
        "state_id": state_id,
        "has_history": any(not version.get("current") for version in versions),
        "versions": versions,
    }


@router.post("/character-ref-versions/restore", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def restore_character_ref_version(
    char_id: str = Query(...),
    version: int = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    from novel_to_comic.stages import s3_cast
    from novel_to_comic.state_assets import (
        mark_dependent_states_stale,
        revalidate_state_asset_lineage,
    )

    project_dir, config, _state = project
    _require_path_safe_id(char_id, "char_id")
    if state_id is not None:
        _require_path_safe_id(state_id, "state_id")
    sheet = _character_ref_sheet_path(project_dir, char_id, state_id)
    try:
        restore_asset_version(sheet, project_dir, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    restore_asset_instruction_direction(project_dir, "character", char_id, state_id, sheet, version, config)
    # The single-view crops (portrait/full_body) are derived from the sheet, so
    # re-crop after restoring so they match.
    s3_cast._crop_sheet_to_poses(sheet)
    if state_id is None:
        mark_dependent_states_stale(project_dir, "character", char_id)
    else:
        revalidate_state_asset_lineage(
            sheet, artifacts.character_ref_sheet_path(project_dir, char_id)
        )
    return {
        "char_id": char_id,
        "state_id": state_id,
        "versions": list_asset_versions(sheet, project_dir),
    }


def _location_history_path(project_dir: Path, loc_id: str, state_id: str | None) -> Path:
    _require_path_safe_id(loc_id, "loc_id")
    if state_id is not None:
        _require_path_safe_id(state_id, "state_id")
    _require_cast_asset(project_dir, "location", loc_id, state_id)
    return (
        artifacts.location_state_plate_path(project_dir, loc_id, state_id)
        if state_id else artifacts.location_plate_path(project_dir, loc_id)
    )


@router.get("/location-plate-versions")
def get_location_plate_versions(
    loc_id: str = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    """Saved location versions, scoped to the main or selected alternate appearance."""
    project_dir, _config, _state = project
    plate = _location_history_path(project_dir, loc_id, state_id)
    versions = list_asset_versions(plate, project_dir)
    return {
        "loc_id": loc_id,
        "state_id": state_id,
        "has_history": any(not version.get("current") for version in versions),
        "versions": versions,
    }


@router.post("/location-plate-versions/restore", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def restore_location_plate_version(
    loc_id: str = Query(...),
    version: int = Query(..., ge=1),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    from novel_to_comic.state_assets import (
        mark_dependent_states_stale,
        revalidate_state_asset_lineage,
    )

    project_dir, _config, _state = project
    plate = _location_history_path(project_dir, loc_id, state_id)
    try:
        restore_asset_version(plate, project_dir, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    restore_asset_instruction_direction(project_dir, "location", loc_id, state_id, plate, version)
    if state_id is None:
        mark_dependent_states_stale(project_dir, "location", loc_id)
    else:
        revalidate_state_asset_lineage(
            plate, artifacts.location_plate_path(project_dir, loc_id)
        )
    return {
        "loc_id": loc_id,
        "state_id": state_id,
        "versions": list_asset_versions(plate, project_dir),
    }
