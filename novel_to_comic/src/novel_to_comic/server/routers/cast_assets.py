"""Per-asset regeneration and version history for the Cast station.

The Cast stage generates every character sheet, appearance state, location
plate, and prop reference in one run. These routes are the follow-up: an author
looking at one bad asset re-rolls it, edits it with an instruction, or restores
an earlier version — without re-running the stage.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic import artifacts
from novel_to_comic.cast_reference_inputs import CastReferenceInput
from novel_to_comic.asset_versions import list_asset_versions, restore_asset_version
from novel_to_comic.cast_instructions import (
    ASSET_REGEN_KINDS,
    MAX_INSTRUCTION_CHARS,
    apply_asset_instruction,
    asset_regen_label,
    resolve_cast_asset,
    restore_asset_instruction_direction,
)

from ..auth import get_current_user
from ..credited_job import enqueue_credited_job
from ..credits import UnifiedCostResolver
from ..codex_admission import image_operations
from novel_to_comic.codex_dev import CodexRoutingError
from ..db import get_db
from ..deps import get_project, project_key
from ..generation_jobs import (
    generation_job_payload,
    generation_semaphore_for_config,
)
from ..ratelimit import cost_limit, limiter

router = APIRouter()


class CastInstructionRequest(BaseModel):
    # Reject mismatched request fields instead of silently dropping attachments
    # and charging for a correction that cannot honor the author's request.
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=MAX_INSTRUCTION_CHARS)
    reference_assets: list[CastReferenceInput] | None = Field(default=None, max_length=3)


class InstructedRefRegenRequest(CastInstructionRequest):
    char_id: str = Field(min_length=1)


class InstructedPlateRegenRequest(CastInstructionRequest):
    loc_id: str = Field(min_length=1)


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


def _enqueue_cast_asset_regen(
    request: Request,
    project_id: str,
    user_id: str,
    project,
    *,
    kind: str,
    asset_id_key: str,
    asset_id: str,
    label: str,
    work,
    debit_description: str,
) -> dict:
    """One intake for cast asset regens — the ref, plate, and prop handlers
    differ only in kind, payload key, and work callable."""
    project_dir, config, _state = project
    pkey = project_key(user_id, project_id)

    # Credit pre-check: each cast regen calls the image model for real and is
    # debited on success. estimate_credits>0 also makes enqueue_credited_job
    # run assert_sufficient_credits, blocking zero-balance users up front.
    asset_estimate = UnifiedCostResolver.estimate_asset_regen_cost(
        config, project_dir, kind, asset_id
    )

    job, _created = enqueue_credited_job(
        request.app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        stage="cast",
        kind=kind,
        label=label,
        payload={asset_id_key: asset_id},
        work=work,
        debit_description=debit_description,
        semaphore=generation_semaphore_for_config(request.app, config),
        estimate_credits=asset_estimate["estimate_credits"],
        operations=image_operations(config),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        asset_id_key: asset_id,
    }


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
    regen_kind = ASSET_REGEN_KINDS.get(asset_type)
    if regen_kind is None:
        valid = ", ".join(ASSET_REGEN_KINDS)
        raise HTTPException(400, f"Unknown asset_type: {asset_type}. Valid: {valid}")
    _require_path_safe_id(asset_id, "asset_id")
    if state_id is not None:
        if asset_type == "prop":
            raise HTTPException(400, "state_id is not supported for prop assets")
        _require_path_safe_id(state_id, "state_id")

    project_dir, config, _state = project
    _require_cast_asset(project_dir, asset_type, asset_id, state_id)
    resolver_asset_id = f"{asset_id}:{state_id}" if state_id else asset_id
    breakdown = UnifiedCostResolver.estimate_asset_regen_cost(
        config, project_dir, regen_kind, resolver_asset_id, additional_reference_count=reference_count
    )
    try:
        instruction_estimate = UnifiedCostResolver.estimate_instructed_regen_cost(
            config, breakdown, "cast"
        )
    except CodexRoutingError as exc:
        instruction_estimate = {"supported": False, "error": str(exc)}
    return {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "state_id": state_id,
        "reference_assets_supported": True,
        **breakdown,
        "instruction_estimate": instruction_estimate,
    }


@router.post("/regen-ref")
@limiter.limit(cost_limit)
async def regen_ref(
    request: Request,
    project_id: str,
    char_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast

    project_dir, config, _state = project
    _require_path_safe_id(char_id, "char_id")
    _require_cast_asset(project_dir, "character", char_id)
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="character_ref_regen",
        asset_id_key="char_id",
        asset_id=char_id,
        label=asset_regen_label("character", char_id),
        work=lambda: s3_cast.regenerate_character_ref(config, project_dir, char_id),
        debit_description=f"Model call: regenerate character ref {char_id}",
    )


@router.post("/regen-state-ref")
@limiter.limit(cost_limit)
async def regen_state_ref(
    request: Request,
    project_id: str,
    char_id: str = Query(...),
    state_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast

    project_dir, config, _state = project
    _require_path_safe_id(char_id, "char_id")
    _require_path_safe_id(state_id, "state_id")
    _require_cast_asset(project_dir, "character", char_id, state_id)
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="character_ref_regen",
        asset_id_key="char_id",
        asset_id=f"{char_id}:{state_id}",
        label=asset_regen_label("character", char_id, state_id),
        work=lambda: s3_cast.regenerate_character_state_ref(
            config, project_dir, char_id, state_id
        ),
        debit_description=(
            f"Model call: regenerate appearance state {char_id}/{state_id}"
        ),
    )


@router.post("/regen-plate")
@limiter.limit(cost_limit)
async def regen_plate(
    request: Request,
    project_id: str,
    loc_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast

    project_dir, config, _state = project
    _require_path_safe_id(loc_id, "loc_id")
    _require_cast_asset(project_dir, "location", loc_id)
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="location_plate_regen",
        asset_id_key="loc_id",
        asset_id=loc_id,
        label=asset_regen_label("location", loc_id),
        work=lambda: s3_cast.regenerate_location_plate(config, project_dir, loc_id),
        debit_description=f"Model call: regenerate location plate {loc_id}",
    )


@router.post("/locations/{loc_id}/states/{state_id}/regenerate")
@limiter.limit(cost_limit)
async def regenerate_location_state(
    request: Request,
    project_id: str,
    loc_id: str,
    state_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast

    project_dir, config, _state = project
    _require_path_safe_id(loc_id, "loc_id")
    _require_path_safe_id(state_id, "state_id")
    _require_cast_asset(project_dir, "location", loc_id, state_id)
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="location_plate_regen",
        asset_id_key="loc_id",
        asset_id=f"{loc_id}:{state_id}",
        label=asset_regen_label("location", loc_id, state_id),
        work=lambda: s3_cast.regenerate_location_plate(
            config, project_dir, loc_id, state_id=state_id
        ),
        debit_description=f"Model call: regenerate location state {loc_id}/{state_id}",
    )


@router.post("/regen-prop")
@limiter.limit(cost_limit)
async def regen_prop(
    request: Request,
    project_id: str,
    prop_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast

    project_dir, config, _state = project
    _require_path_safe_id(prop_id, "prop_id")
    _require_cast_asset(project_dir, "prop", prop_id)
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="prop_ref_regen",
        asset_id_key="prop_id",
        asset_id=prop_id,
        label=asset_regen_label("prop", prop_id),
        work=lambda: s3_cast.regenerate_prop_ref(config, project_dir, prop_id),
        debit_description=f"Model call: regenerate prop ref {prop_id}",
    )


@router.post("/regen-ref-instructed")
@limiter.limit(cost_limit)
async def regen_ref_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedRefRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, _state = project
    _require_path_safe_id(body.char_id, "char_id")
    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="character",
        asset_id=body.char_id,
        instruction=body.instruction,
        reference_assets=body.reference_assets,
        app=request.app,
    )


@router.post("/regen-plate-instructed")
@limiter.limit(cost_limit)
async def regen_plate_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPlateRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, _state = project
    _require_path_safe_id(body.loc_id, "loc_id")
    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="location",
        asset_id=body.loc_id,
        instruction=body.instruction,
        reference_assets=body.reference_assets,
        app=request.app,
    )


@router.post("/regen-prop-instructed")
@limiter.limit(cost_limit)
async def regen_prop_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPropRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, _state = project
    _require_path_safe_id(body.prop_id, "prop_id")
    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="prop",
        asset_id=body.prop_id,
        instruction=body.instruction,
        reference_assets=body.reference_assets,
        app=request.app,
    )


@router.post("/characters/{char_id}/states/{state_id}/regenerate-instructed")
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
    project_dir, config, _state = project
    _require_path_safe_id(char_id, "char_id")
    _require_path_safe_id(state_id, "state_id")
    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="character",
        asset_id=char_id,
        state_id=state_id,
        instruction=body.instruction,
        reference_assets=body.reference_assets,
        app=request.app,
    )


@router.post("/locations/{loc_id}/states/{state_id}/regenerate-instructed")
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
    project_dir, config, _state = project
    _require_path_safe_id(loc_id, "loc_id")
    _require_path_safe_id(state_id, "state_id")
    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="location",
        asset_id=loc_id,
        state_id=state_id,
        instruction=body.instruction,
        reference_assets=body.reference_assets,
        app=request.app,
    )


def _character_ref_sheet_path(
    project_dir: Path, char_id: str, state_id: str | None
) -> Path:
    base = project_dir / "refs" / char_id
    return base / "states" / state_id / "sheet.png" if state_id else base / "sheet.png"


@router.get("/character-ref-versions")
def get_character_ref_versions(
    char_id: str = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    """Archived re-roll history for a character ref sheet (canonical or a state)."""
    project_dir, _config, _state = project
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


@router.post("/character-ref-versions/restore")
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

    project_dir, _config, _state = project
    _require_path_safe_id(char_id, "char_id")
    if state_id is not None:
        _require_path_safe_id(state_id, "state_id")
    sheet = _character_ref_sheet_path(project_dir, char_id, state_id)
    try:
        restore_asset_version(sheet, project_dir, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    restore_asset_instruction_direction(project_dir, "character", char_id, state_id, sheet, version)
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


@router.post("/location-plate-versions/restore")
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
