"""Pipeline execution, SSE streaming, and checkpoint approval."""

import asyncio
from datetime import UTC, datetime
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from novel_to_comic import artifacts
from novel_to_comic.config import Config, config_for_image_model_alias, mock_mode_active
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.stages import REGISTRY
from novel_to_comic.state import (
    STAGE_NAMES,
    StageState,
    StageStatus,
    approve_stage,
    fail_stage,
    get_stale_stages,
    reset_stale_stages,
    save_state,
)
from novel_to_comic.stage_runtime import StageRuntime

from ..auth import get_current_user
from ..credits import (
    CreditEstimate,
    UnifiedCostResolver,
    assert_sufficient_credits,
    estimate_stage_credit_reservation,
    release_stage_reservations,
    credit_estimate_for_provider_cost,
)
from ..db import get_db
from ..deps import get_project, project_key
from ..ratelimit import cost_limit, limiter
from ..credited_job import (
    CreditReservationDenied,
    enqueue_credited_job,
    run_credited_stage,
)
from novel_to_comic.panel_generation import (
    compile_panel_request,
    estimate_panel_request,
    prepare_panel_request,
    submit_panel_request,
)
from novel_to_comic.frozen_requests import (
    FrozenRequestError,
    FrozenRequestNotFound,
    load_frozen_request,
    submit_frozen_request,
)
from novel_to_comic.generation_request_preview import (
    compiled_request_context,
    frozen_request_preview,
)
from ..generation_jobs import (
    generation_job_payload,
    generation_semaphore_for_config,
)
from ..panel_acceptance import clear_panel_acceptance
from ..panel_flags import clear_panel_flag
from ..product_events import capture_server_event
from ..metrics import increment, observe

router = APIRouter()
logger = logging.getLogger("canary.pipeline")

_ASSET_REGEN_KINDS = {
    "character": "character_ref_regen",
    "location": "location_plate_regen",
    "prop": "prop_ref_regen",
}
_GENERATED_ENTITY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def _panel_regen_config_for_alias(
    config: Config, image_model_alias: str | None
) -> Config:
    try:
        return config_for_image_model_alias(config, image_model_alias)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _validate_panel_scene_id(scene_id: str) -> None:
    if not scene_id or scene_id != Path(scene_id).name or scene_id in {".", ".."}:
        raise HTTPException(400, "Invalid scene_id")


def _validate_generated_entity_id(value: str, field_name: str) -> None:
    if not _GENERATED_ENTITY_ID_RE.fullmatch(value):
        raise HTTPException(400, f"Invalid {field_name}")


class InstructedPanelRegenRequest(BaseModel):
    scene_id: str = Field(min_length=1)
    panel_number: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=500)
    image_model_alias: str | None = None


class PreparePanelRequest(BaseModel):
    scene_id: str = Field(min_length=1)
    panel_number: int = Field(ge=1)
    image_model_alias: str | None = None


class InstructedRefRegenRequest(BaseModel):
    char_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedPlateRegenRequest(BaseModel):
    loc_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedStateRegenRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=500)


class InstructedPropRegenRequest(BaseModel):
    prop_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


def _compile_panel_projection(
    project_dir: Path,
    config: Config,
    scene_id: str,
    panel_number: int,
    image_model_alias: str | None,
):
    """Compile current persisted inputs without hydrating or calling a model."""
    _validate_panel_scene_id(scene_id)
    regen_config = _panel_regen_config_for_alias(config, image_model_alias)
    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")
    try:
        prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    except Exception as exc:
        raise HTTPException(422, "Stored panel prompt is invalid") from exc
    from novel_to_comic.stages.s7_draw import _find_style_sample

    style_sample = _find_style_sample(project_dir, regen_config.style_template)
    return regen_config, compile_panel_request(
        regen_config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        output_dir=project_dir / "draw" / scene_id,
    )


def _wrap_on_event(queue: asyncio.Queue, app_state, pkey: str):
    """Build an event handler that pushes to the SSE queue and also
    maintains ``app_state.draw_in_flight[pkey]`` for panel-level events.

    Stage code stays framework-agnostic — it only emits dict events. The
    in-flight map is the server's view of which panels are mid-generation
    right now, surfaced in the /status payload so a fresh page load shows
    the live cockpit immediately.
    """
    in_flight_map: dict[str, list[dict]] = app_state.draw_in_flight

    def handler(event: dict) -> None:
        queue.put_nowait(event)
        if event.get("stage") != "draw":
            return
        evt_type = event.get("type")
        if evt_type == "panel_start":
            in_flight_map.setdefault(pkey, []).append(
                {
                    "scene_id": event["scene_id"],
                    "panel_number": event["panel_number"],
                    "started_at": event["started_at"],
                }
            )
        elif evt_type == "panel_done":
            existing = in_flight_map.get(pkey, [])
            in_flight_map[pkey] = [
                e
                for e in existing
                if not (
                    e["scene_id"] == event["scene_id"]
                    and e["panel_number"] == event["panel_number"]
                )
            ]
        elif evt_type in ("stage_complete", "stage_fail"):
            in_flight_map.pop(pkey, None)

    return handler


async def _run_stage(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    app_state,
    pkey: str,
    *,
    retry_failed: bool = False,
):
    """Execute a single stage, feeding events into the queue."""
    started = time.perf_counter()
    logger.info(
        "[bold cyan]Stage start[/] project=[white]%s[/] stage=[bold]%s[/]",
        project_dir.name,
        stage,
    )
    try:
        stage_obj = REGISTRY.get(stage)
        if not stage_obj:
            raise ValueError(f"Unknown stage: {stage}")
        extra_kwargs: dict = {}
        if retry_failed and stage == "draw":
            extra_kwargs["retry_failed"] = True
        ctx = StageRuntime(
            stage,
            state,
            project_dir,
            on_event=_wrap_on_event(queue, app_state, pkey),
        )
        await stage_obj.run(config, project_dir, ctx, **extra_kwargs)
        elapsed = time.perf_counter() - started
        status = state.stages[stage].status.value
        status_color = (
            "green" if status in {"complete", "awaiting_review"} else "yellow"
        )
        logger.info(
            "[bold green]Stage end[/] project=[white]%s[/] stage=[bold]%s[/] "
            "status=[%s]%s[/] elapsed=[bold]%.1fs[/]",
            project_dir.name,
            stage,
            status_color,
            status,
            elapsed,
        )
    except Exception as exc:
        from novel_to_comic.text_utils import clean_exception_message
        from novel_to_comic.ai.errors import AITransportError

        message = clean_exception_message(exc)
        # StageRuntime.execute() already called fail_stage + save_state + emitted stage_fail.
        # This catch handles the case where a stage raises before entering execute().
        if state.stages[stage].status.value not in ("failed",):
            fail_stage(state, stage, message)
            save_state(state, project_dir)
            queue.put_nowait({"type": "stage_fail", "stage": stage, "message": message})
        elapsed = time.perf_counter() - started
        log_args = (project_dir.name, stage, elapsed, message)
        if isinstance(exc, AITransportError):
            logger.warning(
                "[bold yellow]Stage failed (handled provider error)[/] "
                "project=[white]%s[/] stage=[bold]%s[/] elapsed=[bold]%.1fs[/] error=%s",
                *log_args,
            )
        else:
            logger.exception(
                "[bold red]Stage failed[/] project=[white]%s[/] stage=[bold]%s[/] "
                "elapsed=[bold]%.1fs[/] error=%s",
                *log_args,
            )


# Stages that auto-chain: when the first stage completes, the rest run automatically.
# The chain stops at the first failure or awaiting_review checkpoint.
STAGE_AUTO_CHAIN: dict[str, list[str]] = {
    "adapt": ["plan", "storyboard", "direct"],
    "plan": ["storyboard", "direct"],
    "storyboard": ["direct"],
}


def _reset_missing_auto_chain_artifact(stage: str, project_dir, state) -> None:
    """Make a stale completed stage runnable when its canonical output is gone."""
    if stage == "plan" and not artifacts.layout_plan_path(project_dir).exists():
        if state.stages[stage].status in (
            StageStatus.COMPLETE,
            StageStatus.AWAITING_REVIEW,
        ):
            state.stages[stage] = StageState()
            save_state(state, project_dir)


async def _run_stage_with_credits(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    user_id: str,
    project_id: str | None,
    app_state,
    pkey: str,
    *,
    rerun: bool = False,
    retry_failed: bool = False,
):
    """Run the stage behind a credit guarantee, then auto-chain."""
    started = time.perf_counter()
    capture_server_event(
        "stage_started",
        user_id=user_id,
        project_id=project_id,
        properties={"stage": stage, "rerun": rerun, "retry_failed": retry_failed},
    )
    try:
        job_id = await run_credited_stage(
            user_id=user_id,
            project_id=project_id,
            project_dir=project_dir,
            config=config,
            state=state,
            stage=stage,
            run=lambda: _run_stage(
                stage,
                config,
                project_dir,
                state,
                queue,
                app_state,
                pkey,
                retry_failed=retry_failed,
            ),
        )
    except CreditReservationDenied as denied:
        # Insufficient credits or DB error — fail the stage so the UI reflects it.
        fail_stage(state, stage, denied.message, detail=denied.detail)
        save_state(state, project_dir)
        event: dict[str, object] = {
            "type": "stage_fail",
            "stage": stage,
            "message": denied.message,
        }
        if denied.detail and denied.detail.get("error") == "insufficient_credits":
            event["error_code"] = "insufficient_credits"
            event["balance_credits"] = denied.detail.get("balance_credits")
            event["required_credits"] = denied.detail.get("required_credits")
            event["shortfall_credits"] = denied.detail.get("shortfall_credits")
        queue.put_nowait(event)
        capture_server_event(
            "stage_failed",
            user_id=user_id,
            project_id=project_id,
            properties={"stage": stage, "error_type": "credit_reservation_denied"},
        )
        increment("canary_stage_runs_total", stage=stage, outcome="failed")
        observe(
            "canary_stage_duration_seconds",
            time.perf_counter() - started,
            stage=stage,
            outcome="failed",
        )
        return
    except Exception as exc:
        capture_server_event(
            "stage_failed",
            user_id=user_id,
            project_id=project_id,
            properties={"stage": stage, "error_type": type(exc).__name__},
        )
        increment("canary_stage_runs_total", stage=stage, outcome="failed")
        observe(
            "canary_stage_duration_seconds",
            time.perf_counter() - started,
            stage=stage,
            outcome="failed",
        )
        raise

    s = state.stages[stage]
    if s.status == StageStatus.FAILED:
        capture_server_event(
            "stage_failed",
            user_id=user_id,
            project_id=project_id,
            job_id=job_id,
            properties={"stage": stage, "error_type": s.error_code or "stage_failed"},
        )
        increment("canary_stage_runs_total", stage=stage, outcome="failed")
        observe(
            "canary_stage_duration_seconds",
            time.perf_counter() - started,
            stage=stage,
            outcome="failed",
        )
        return
    outcome = "awaiting_review" if s.status == StageStatus.AWAITING_REVIEW else "succeeded"
    capture_server_event(
        "stage_succeeded",
        user_id=user_id,
        project_id=project_id,
        job_id=job_id,
        properties={"stage": stage, "outcome": outcome},
    )
    increment("canary_stage_runs_total", stage=stage, outcome=outcome)
    observe(
        "canary_stage_duration_seconds",
        time.perf_counter() - started,
        stage=stage,
        outcome=outcome,
    )

    # Auto-chain: if the stage completed (not awaiting_review, not failed),
    # automatically run the next stages in the chain.
    if s.status == StageStatus.COMPLETE and stage in STAGE_AUTO_CHAIN:
        for next_stage in STAGE_AUTO_CHAIN[stage]:
            _reset_missing_auto_chain_artifact(next_stage, project_dir, state)
            next_s = state.stages[next_stage]
            if next_s.status != StageStatus.PENDING:
                continue
            await _run_stage_with_credits(
                next_stage,
                config,
                project_dir,
                state,
                queue,
                user_id,
                project_id,
                app_state,
                pkey,
                rerun=rerun,
            )
            # Stop if the chained stage failed or hit a review checkpoint
            if state.stages[next_stage].status in (
                StageStatus.FAILED,
                StageStatus.AWAITING_REVIEW,
            ):
                break


async def _run_job(pkey: str, request: Request, job):
    """Wrap a pipeline task so lifecycle cleanup is consistent."""
    try:
        await job
    finally:
        queue = request.app.state.event_queues.get(pkey)
        if queue is not None:
            queue.put_nowait({"type": "pipeline_done"})
        request.app.state.running_tasks.pop(pkey, None)
        # Schedule cleanup of the event queue if no SSE client drains it.
        # This prevents orphaned queues when a client disconnects before
        # receiving pipeline_done.
        asyncio.get_event_loop().call_later(
            60,
            _cleanup_stale_queue,
            request.app,
            pkey,
            queue,
        )


def _cleanup_stale_queue(app, pkey: str, queue) -> None:
    """Remove an event queue if it's still the same one and no task owns it."""
    current = app.state.event_queues.get(pkey)
    if current is not queue:
        return  # a new run replaced it
    task = app.state.running_tasks.get(pkey)
    if task is not None and not task.done():
        return  # a new run is active
    app.state.event_queues.pop(pkey, None)


def _reset_stage_and_downstream(state, stage: str) -> None:
    stage_idx = STAGE_NAMES.index(stage)
    for stage_name in STAGE_NAMES[stage_idx:]:
        state.stages[stage_name] = StageState()


def _clear_outputs_for_rerun(project_dir, stage: str) -> None:
    stage_obj = REGISTRY.get(stage)
    if not stage_obj:
        return
    for path in stage_obj.clean_paths(project_dir):
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _draw_panel_blockers_for_compose(project_dir) -> list[str]:
    """Return prompt-backed draw panels that must be regenerated before compose."""
    direct_dir = project_dir / "direct"
    if not direct_dir.exists():
        return []

    blockers: list[str] = []
    for prompt_path in sorted(direct_dir.glob("*/panel_*.json")):
        scene_id = prompt_path.parent.name
        try:
            prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
            panel_number = prompt.panel_number
        except Exception:
            try:
                panel_number = int(prompt_path.stem.split("_")[1])
            except (IndexError, ValueError):
                continue

        image_path = artifacts.panel_image_path(project_dir, scene_id, panel_number)
        if artifacts.asset_failure_path(image_path).exists():
            blockers.append(f"{scene_id}/panel_{panel_number:03d} failed")
        elif not image_path.exists():
            blockers.append(f"{scene_id}/panel_{panel_number:03d} missing image")

    return blockers


def _draw_ready_for_compose_error(project_dir) -> str | None:
    blockers = _draw_panel_blockers_for_compose(project_dir)
    if not blockers:
        return None
    shown = ", ".join(blockers[:5])
    if len(blockers) > 5:
        shown = f"{shown}, and {len(blockers) - 5} more"
    return f"Regenerate failed or missing draw panels before composing: {shown}"


def _append_instruction_log(
    project_dir,
    scene_id: str,
    panel_number: int,
    *,
    instruction: str,
    patch: dict,
    prompt: ImagePrompt,
) -> None:
    log_path = artifacts.panel_prompt_instructions_path(
        project_dir, scene_id, panel_number
    )
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "instruction": instruction,
        "patch": patch,
        "prompt": {
            "scene_id": prompt.scene_id,
            "panel_number": prompt.panel_number,
            "full_prompt": prompt.full_prompt,
        },
    }
    with log_path.open("a") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


@router.get("/estimate")
async def estimate_stage_cost(
    project_id: str,
    stage: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Return the estimated credit breakdown for running a stage (and its auto-chain)."""
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    project_dir, config, state = project

    # Sum costs for the stage and all stages it will auto-chain into.
    chain = [stage] + STAGE_AUTO_CHAIN.get(stage, [])
    breakdown = UnifiedCostResolver.estimate_stage_cost(
        config, project_dir, state, chain[0]
    )
    for chained in chain[1:]:
        extra = UnifiedCostResolver.estimate_stage_cost(
            config, project_dir, state, chained
        )
        breakdown = CreditEstimate(
            estimate_credits=breakdown["estimate_credits"] + extra["estimate_credits"],
            reserved_credits=(breakdown["reserved_credits"] or 0)
            + (extra["reserved_credits"] or 0),
            reservation_multiplier=breakdown["reservation_multiplier"],
            confidence=breakdown["confidence"],
        )

    return {"stage": stage, **breakdown}


@router.get("/regen-estimate")
async def regen_panel_estimate(
    project_id: str,
    scene_id: str = Query(...),
    panel_number: int = Query(...),
    image_model_alias: str | None = Query(None),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Return the estimated credit cost to regenerate one panel image."""
    _validate_panel_scene_id(scene_id)
    project_dir, config, _state = project
    breakdown = UnifiedCostResolver.estimate_panel_regen_cost(
        config, project_dir, scene_id, panel_number, image_model_alias
    )
    instruction_estimate = UnifiedCostResolver.estimate_instructed_regen_cost(
        config, breakdown, "draw"
    )
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        **breakdown,
        "instruction_estimate": instruction_estimate,
    }


@router.get("/asset-regen-estimate")
async def regen_cast_asset_estimate(
    project_id: str,
    asset_type: str = Query(...),
    asset_id: str = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the estimated credit cost to regenerate one cast asset."""
    regen_kind = _ASSET_REGEN_KINDS.get(asset_type)
    if regen_kind is None:
        valid = ", ".join(_ASSET_REGEN_KINDS)
        raise HTTPException(400, f"Unknown asset_type: {asset_type}. Valid: {valid}")
    _validate_generated_entity_id(asset_id, "asset_id")
    if state_id is not None:
        if asset_type == "prop":
            raise HTTPException(400, "state_id is not supported for prop assets")
        _validate_generated_entity_id(state_id, "state_id")

    project_dir, config, _state = project
    resolver_asset_id = f"{asset_id}:{state_id}" if state_id else asset_id
    breakdown = UnifiedCostResolver.estimate_asset_regen_cost(
        config, project_dir, asset_type=regen_kind, asset_id=resolver_asset_id,
    )
    instruction_estimate = UnifiedCostResolver.estimate_instructed_regen_cost(
        config, breakdown, "cast"
    )
    return {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "state_id": state_id,
        **breakdown,
        "instruction_estimate": instruction_estimate,
    }


@router.get("/generation-requests/preview")
def preview_generation_request(
    project_id: str,
    scene_id: str = Query(...),
    panel_number: int = Query(..., ge=1),
    image_model_alias: str | None = Query(None),
    prepared_request_id: str | None = Query(None),
    dev_content: bool = Query(False),
    project=Depends(get_project),
):
    """Return a deterministic, non-exact projection unless a frozen request matches."""
    project_dir, config, _state = project
    _regen_config, panel_request = _compile_panel_projection(
        project_dir, config, scene_id, panel_number, image_model_alias,
    )
    draft = {
        "prompt": panel_request.compiled.final_prompt,
        "warnings": [*panel_request.compiled.warnings, "preparation outstanding"],
        "reference_count": len(panel_request.reference_plan.selected),
    }
    if not prepared_request_id:
        return frozen_request_preview(None, draft=draft)

    try:
        frozen = load_frozen_request(project_dir, prepared_request_id)
    except FrozenRequestNotFound as exc:
        raise HTTPException(404, "Generation request not found") from exc
    except FrozenRequestError as exc:
        raise HTTPException(409, "Generation request failed integrity checks") from exc

    if frozen.execution_fingerprint != panel_request.wire.execution_fingerprint:
        result = frozen_request_preview(
            None,
            draft={
                **draft,
                "warnings": [
                    *draft["warnings"],
                    "prepared request is stale after an authoritative source change",
                ],
            },
        )
        if dev_content:
            result["prepared_request_id"] = prepared_request_id
            result["stale"] = True
        return result
    return frozen_request_preview(
        frozen,
        include_dev_content=dev_content,
        project_dir=project_dir,
    )


@router.post("/generation-requests/prepare")
def prepare_generation_request(
    body: PreparePanelRequest,
    project_id: str,
    project=Depends(get_project),
):
    """Freeze one exact panel request without reserving credits or generating art."""
    project_dir, config, _state = project
    _regen_config, panel_request = _compile_panel_projection(
        project_dir,
        config,
        body.scene_id,
        body.panel_number,
        body.image_model_alias,
    )
    context = compiled_request_context(panel_request.compiled)
    estimate = estimate_panel_request(
        _regen_config,
        project_dir,
        panel_request.prompt,
        reference_plan=panel_request.reference_plan,
        prepared=True,
    )
    estimate_credits = credit_estimate_for_provider_cost(
        0.0 if mock_mode_active(_regen_config) else estimate.cost_usd,
        "draw",
        reserve=False,
        zero_cost_estimate=0 if mock_mode_active(_regen_config) else 1,
    )["estimate_credits"]
    fingerprint = panel_request.wire.execution_fingerprint
    frozen = submit_frozen_request(
        project_dir,
        panel_request.wire,
        idempotency_key=(
            f"prepare:panel:{body.scene_id}:{body.panel_number}:{fingerprint}"
        ),
        status="prepared",
        request_context=context,
    )
    preview = frozen_request_preview(
        frozen,
        include_dev_content=False,
        project_dir=project_dir,
    )
    preview["request_id"] = frozen.request_id
    preview["accounting"] = {
        "estimated_cost_usd": estimate.cost_usd,
        "estimated_credits": estimate_credits,
        "reserved": False,
        "charge_on": "explicit generation submission",
    }
    return preview


@router.get("/generation-requests/{request_id}")
def get_generation_request(
    request_id: str,
    dev_content: bool = Query(False),
    project=Depends(get_project),
):
    """Read an authorized immutable request and optional completed provenance."""
    project_dir, _config, _state = project
    try:
        frozen = load_frozen_request(project_dir, request_id)
    except FrozenRequestNotFound as exc:
        raise HTTPException(404, "Generation request not found") from exc
    except FrozenRequestError as exc:
        raise HTTPException(409, "Generation request failed integrity checks") from exc
    return frozen_request_preview(
        frozen,
        include_dev_content=dev_content,
        project_dir=project_dir,
    )


@router.post("/run")
@limiter.limit(cost_limit)
async def run_pipeline(
    request: Request,
    project_id: str,
    stage: Optional[str] = Query(None),
    rerun: bool = Query(False),
    retry_failed: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    if stage and stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    if rerun and not stage:
        raise HTTPException(400, "rerun=true requires a specific stage")
    if retry_failed and stage != "draw":
        raise HTTPException(400, "retry_failed=true is only supported for stage=draw")
    if retry_failed and rerun:
        raise HTTPException(400, "retry_failed and rerun are mutually exclusive")

    # Concurrency guard
    running = request.app.state.running_tasks
    existing = running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")
    existing_style = request.app.state.style_tasks.get(pkey)
    if existing_style and not existing_style.done():
        raise HTTPException(
            409, "A style operation is already running for this project"
        )

    if stage == "compose":
        draw_error = _draw_ready_for_compose_error(project_dir)
        if draw_error:
            raise HTTPException(409, draw_error)

    if not stage:
        raise HTTPException(400, "stage parameter is required")

    # Gate: post-style stages require a style to have been selected
    _POST_STYLE_STAGES = {
        "cast",
        "adapt",
        "plan",
        "storyboard",
        "direct",
        "draw",
        "compose",
    }
    if stage in _POST_STYLE_STAGES:
        from ..routers.styles import is_style_selected

        if not is_style_selected(project_dir, config):
            raise HTTPException(
                403,
                "Style must be selected before running post-style stages. "
                "Pick a style first.",
            )

    if stage and rerun:
        _reset_stage_and_downstream(state, stage)
        _clear_outputs_for_rerun(project_dir, stage)
        save_state(state, project_dir)

    # Pre-check that the user can afford the stage (and its first auto-chain step,
    # which would otherwise fail mid-run). Atomic reservation still happens inside
    # the task — this is just the fast path that returns 402 with structured detail
    # so the client can render a "buy more credits" prompt before any work starts.
    db = get_db()
    required_credits = estimate_stage_credit_reservation(
        config, project_dir, state, stage
    )
    assert_sufficient_credits(db, user_id, required_credits, stage=stage)

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue

    job = _run_stage_with_credits(
        stage,
        config,
        project_dir,
        state,
        queue,
        user_id,
        project_id,
        request.app.state,
        pkey,
        rerun=rerun,
        retry_failed=retry_failed,
    )

    task = asyncio.create_task(_run_job(pkey, request, job))

    running[pkey] = task
    logger.info(
        "[bold blue]Pipeline queued[/] project=[white]%s[/] stage=[bold]%s[/]",
        project_dir.name,
        stage or "all",
    )
    return {"status": "started", "stage": stage or "all"}


@router.post("/regen-extract")
@limiter.limit(cost_limit)
async def regen_extract(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    # Concurrency guard
    running = request.app.state.running_tasks
    existing = running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")
    existing_style = request.app.state.style_tasks.get(pkey)
    if existing_style and not existing_style.done():
        raise HTTPException(
            409, "A style operation is already running for this project"
        )

    # Keep behavior aligned with /run?stage=extract&rerun=1:
    # reset extract + all downstream stage state, and clear downstream outputs.
    _reset_stage_and_downstream(state, "extract")
    _clear_outputs_for_rerun(project_dir, "extract")
    save_state(state, project_dir)

    db = get_db()
    required_credits = estimate_stage_credit_reservation(
        config, project_dir, state, "extract"
    )
    assert_sufficient_credits(db, user_id, required_credits, stage="extract")

    # Run extract stage via SSE pipeline (same pattern as POST /run?stage=extract)
    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue
    job = _run_stage_with_credits(
        "extract",
        config,
        project_dir,
        state,
        queue,
        user_id,
        project_id,
        request.app.state,
        pkey,
        rerun=True,
    )
    task = asyncio.create_task(_run_job(pkey, request, job))
    running[pkey] = task
    logger.info(
        "[bold blue]Pipeline queued[/] project=[white]%s[/] stage=[bold]extract[/] mode=regen",
        project_dir.name,
    )

    return {"status": "started", "stage": "extract"}


@router.get("/events")
async def event_stream(
    request: Request,
    project_id: str,
    user_id: str = Depends(get_current_user),
):
    pkey = project_key(user_id, project_id)
    queue = request.app.state.event_queues.get(pkey)
    if not queue:
        raise HTTPException(404, "No active run for this project")

    async def generator():
        completed = False
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
                    continue

                yield f"data: {json.dumps(event)}\n\n"

                if event.get("type") == "pipeline_done":
                    completed = True
                    break
        finally:
            task = request.app.state.running_tasks.get(pkey)
            current_queue = request.app.state.event_queues.get(pkey)
            if current_queue is queue and (completed or task is None or task.done()):
                request.app.state.event_queues.pop(pkey, None)

    return StreamingResponse(generator(), media_type="text/event-stream")


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
    """One intake for cast asset regens — ref, plate, and prop handlers
    differ only in kind, payload key, and work callable."""
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    # Credit pre-check: each cast regen calls the image model for real and is
    # debited on success. estimate_credits>0 also makes enqueue_credited_job
    # run assert_sufficient_credits, blocking zero-balance users up front.
    asset_estimate = UnifiedCostResolver.estimate_asset_regen_cost(
        config, project_dir, asset_type=kind, asset_id=asset_id,
    )

    job, _ = enqueue_credited_job(
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
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        asset_id_key: asset_id,
    }


@router.post("/regen")
@limiter.limit(cost_limit)
async def regen_panel(
    request: Request,
    project_id: str,
    scene_id: str = Query(...),
    panel_number: int = Query(...),
    image_model_alias: str | None = Query(None),
    prepared_request_id: str | None = Query(None),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    _validate_panel_scene_id(scene_id)
    regen_config = _panel_regen_config_for_alias(config, image_model_alias)
    pkey = project_key(user_id, project_id)

    running = request.app.state.running_tasks
    existing_stage = running.get(pkey)
    if existing_stage and not existing_stage.done():
        raise HTTPException(409, "A stage is already running for this project")

    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not prompt_path.exists():
        raise HTTPException(
            404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}"
        )
    planned_panel_id = None
    try:
        planned_panel_id = ImagePrompt.model_validate_json(
            prompt_path.read_text()
        ).planned_panel_id
    except Exception:
        planned_panel_id = None

    if prepared_request_id:
        # A prepared request already contains the exact semantic and provider
        # inputs. Recompile only the current persisted projection to detect
        # staleness; never hydrate missing derived fields during consumption.
        regen_config, panel_request = _compile_panel_projection(
            project_dir,
            config,
            scene_id,
            panel_number,
            image_model_alias,
        )
        style_sample = None
    else:
        style_sample = None
        from novel_to_comic.stages.s7_draw import _find_style_sample
        style_sample = _find_style_sample(project_dir, regen_config.style_template)
        panel_request = await prepare_panel_request(
            regen_config,
            project_dir,
            prompt_path,
            style_sample=style_sample,
        )
    request_idempotency_key = (
        f"panel_regen:{scene_id}:{panel_number}:{panel_request.wire.execution_fingerprint}"
    )
    if prepared_request_id:
        try:
            prepared = load_frozen_request(project_dir, prepared_request_id)
        except FrozenRequestNotFound as exc:
            raise HTTPException(404, "Prepared generation request not found") from exc
        except FrozenRequestError as exc:
            raise HTTPException(409, "Prepared generation request failed integrity checks") from exc
        if (
            prepared.status == "invalidated"
            or prepared.execution_fingerprint != panel_request.wire.execution_fingerprint
        ):
            raise HTTPException(409, "Prepared generation request is stale; prepare again")
        request_idempotency_key = prepared.idempotency_key or prepared_request_id
    panel_estimate = estimate_panel_request(
        regen_config,
        project_dir,
        panel_request.prompt,
        reference_plan=panel_request.reference_plan,
        prompt_path=prompt_path,
        style_sample=style_sample,
        prepared=True,
    )
    from ..credits import credit_estimate_for_provider_cost
    panel_estimate_credits = credit_estimate_for_provider_cost(
        0.0 if mock_mode_active(regen_config) else panel_estimate.cost_usd,
        "draw", reserve=False,
        zero_cost_estimate=0 if mock_mode_active(regen_config) else 1,
    )["estimate_credits"]
    clear_panel_acceptance(project_dir, scene_id, panel_number)
    clear_panel_flag(project_dir, scene_id, panel_number)
    submission = await submit_panel_request(
        config=regen_config,
        project_dir=project_dir,
        request=panel_request,
        output_path=project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png",
        app=request.app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        stage="draw",
        kind="panel_regen",
        label=f"{scene_id} / panel {panel_number:03d}",
        payload={"scene_id": scene_id, "panel_number": panel_number},
        debit_description=f"Model call: regenerate panel {scene_id}/{panel_number:03d}",
        semaphore=generation_semaphore_for_config(request.app, regen_config),
        estimate_credits=panel_estimate_credits,
        idempotency_key=request_idempotency_key,
    )
    job = submission.job
    created = submission.created
    if job is None:
        raise HTTPException(500, "Panel generation job was not created")
    if created:
        # Immediately clear acceptance so the UI shows the panel as pending
        # before the job starts running (the runner clears it again for safety).
        clear_panel_acceptance(project_dir, scene_id, panel_number)
        clear_panel_flag(project_dir, scene_id, panel_number)
        capture_server_event(
            "panel_regenerated",
            user_id=user_id,
            project_id=project_id,
            job_id=job.id,
            request_id=getattr(request.state, "request_id", None),
            properties={"mode": "prepared" if prepared_request_id else "standard"},
        )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "scene_id": scene_id,
        "panel_number": panel_number,
        "planned_panel_id": planned_panel_id,
        "request_id": submission.request_id,
    }


@router.post("/regen-instructed")
@limiter.limit(cost_limit)
async def regen_panel_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPanelRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    running = request.app.state.running_tasks
    existing_stage = running.get(pkey)
    if existing_stage and not existing_stage.done():
        raise HTTPException(409, "A stage is already running for this project")

    from novel_to_comic.prompt_instructions import apply_asset_instruction

    result = await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="panel",
        asset_id=f"{body.scene_id}:{body.panel_number}",
        instruction=body.instruction,
        app=request.app,
        image_model_alias=body.image_model_alias,
    )
    capture_server_event(
        "panel_regenerated",
        user_id=user_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        properties={"mode": "instructed"},
    )
    return result


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

    _project_dir, config, _state = project
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="character_ref_regen",
        asset_id_key="char_id",
        asset_id=char_id,
        label=f"Character ref / {char_id}",
        work=lambda: s3_cast.regenerate_character_ref(config, _project_dir, char_id),
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

    _project_dir, config, _state = project
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="character_ref_regen",
        asset_id_key="char_id",
        asset_id=f"{char_id}:{state_id}",
        label=f"Appearance state / {char_id} · {state_id}",
        work=lambda: s3_cast.regenerate_character_state_ref(
            config, _project_dir, char_id, state_id
        ),
        debit_description=f"Model call: regenerate appearance state {char_id}/{state_id}",
    )


def _character_ref_sheet_path(project_dir, char_id: str, state_id: str | None):
    base = project_dir / "refs" / char_id
    return base / "states" / state_id / "sheet.png" if state_id else base / "sheet.png"


@router.get("/character-ref-versions")
def get_character_ref_versions(
    char_id: str = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    """Archived re-roll history for a character ref sheet (canonical or a state)."""
    from novel_to_comic.panel_versions import list_asset_versions

    project_dir, _config, _state = project
    sheet = _character_ref_sheet_path(project_dir, char_id, state_id)
    versions = list_asset_versions(sheet, project_dir)
    archived = [version for version in versions if not version.get("current")]
    return {
        "char_id": char_id,
        "state_id": state_id,
        "has_history": len(archived) > 0,
        "versions": versions,
    }


@router.post("/character-ref-versions/restore")
def restore_character_ref_version(
    char_id: str = Query(...),
    version: int = Query(...),
    state_id: str | None = Query(None),
    project=Depends(get_project),
):
    from novel_to_comic.panel_versions import list_asset_versions, restore_asset_version
    from novel_to_comic.stages import s3_cast

    project_dir, _config, _state = project
    sheet = _character_ref_sheet_path(project_dir, char_id, state_id)
    try:
        restore_asset_version(sheet, project_dir, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    # The single-view crops (portrait/full_body) are derived
    # from the sheet, so re-crop after restoring so they match.
    s3_cast._crop_sheet_to_poses(sheet)
    if state_id is None:
        from novel_to_comic.state_assets import mark_dependent_states_stale
        mark_dependent_states_stale(project_dir, "character", char_id)
    else:
        from novel_to_comic.state_assets import revalidate_state_asset_lineage
        revalidate_state_asset_lineage(
            sheet, artifacts.character_ref_sheet_path(project_dir, char_id)
        )
    return {
        "char_id": char_id,
        "state_id": state_id,
        "versions": list_asset_versions(sheet, project_dir),
    }


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

    _project_dir, config, _state = project
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="location_plate_regen",
        asset_id_key="loc_id",
        asset_id=loc_id,
        label=f"Location plate / {loc_id}",
        work=lambda: s3_cast.regenerate_location_plate(config, _project_dir, loc_id),
        debit_description=f"Model call: regenerate location plate {loc_id}",
    )


@router.get("/location-plate-versions")
def get_location_plate_versions(
    loc_id: str = Query(...), project=Depends(get_project),
):
    from novel_to_comic.panel_versions import list_asset_versions
    project_dir, _config, _state = project
    plate = artifacts.location_plate_path(project_dir, loc_id)
    return {"loc_id": loc_id, "versions": list_asset_versions(plate, project_dir)}


@router.post("/location-plate-versions/restore")
def restore_location_plate_version(
    loc_id: str = Query(...), version: int = Query(...),
    project=Depends(get_project),
):
    from novel_to_comic.panel_versions import list_asset_versions, restore_asset_version
    from novel_to_comic.state_assets import mark_dependent_states_stale
    project_dir, _config, _state = project
    plate = artifacts.location_plate_path(project_dir, loc_id)
    try:
        restore_asset_version(plate, project_dir, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    warnings = mark_dependent_states_stale(project_dir, "location", loc_id)
    return {"loc_id": loc_id, "versions": list_asset_versions(plate, project_dir), "lineage_warnings": warnings}


@router.post("/locations/{loc_id}/states/{state_id}/regenerate")
@limiter.limit(cost_limit)
async def regenerate_location_state(
    request: Request, project_id: str, loc_id: str, state_id: str,
    project=Depends(get_project), user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast
    project_dir, config, _state = project
    return _enqueue_cast_asset_regen(
        request, project_id, user_id, project, kind="location_plate_regen",
        asset_id_key="loc_id", asset_id=f"{loc_id}:{state_id}",
        label=f"Location state / {loc_id} · {state_id}",
        work=lambda: s3_cast.regenerate_location_plate(
            config, project_dir, loc_id, state_id=state_id
        ),
        debit_description=f"Model call: regenerate location state {loc_id}/{state_id}",
    )


@router.post("/characters/{char_id}/states/{state_id}/regenerate")
@limiter.limit(cost_limit)
async def regenerate_character_state(
    request: Request, project_id: str, char_id: str, state_id: str,
    project=Depends(get_project), user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s3_cast
    project_dir, config, _state = project
    return _enqueue_cast_asset_regen(
        request, project_id, user_id, project, kind="character_ref_regen",
        asset_id_key="char_id", asset_id=f"{char_id}:{state_id}",
        label=f"Appearance state / {char_id} · {state_id}",
        work=lambda: s3_cast.regenerate_character_state_ref(
            config, project_dir, char_id, state_id
        ),
        debit_description=f"Model call: regenerate appearance state {char_id}/{state_id}",
    )


@router.post("/characters/{char_id}/states/{state_id}/regenerate-instructed")
@limiter.limit(cost_limit)
async def regenerate_character_state_instructed(
    request: Request, project_id: str, char_id: str, state_id: str,
    body: InstructedStateRegenRequest, project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.prompt_instructions import apply_asset_instruction
    project_dir, config, _state = project
    return await apply_asset_instruction(
        config=config, project_dir=project_dir, db=get_db(), user_id=user_id,
        project_id=project_id, asset_type="character", asset_id=char_id,
        state_id=state_id, instruction=body.instruction, app=request.app,
    )


@router.post("/locations/{loc_id}/states/{state_id}/regenerate-instructed")
@limiter.limit(cost_limit)
async def regenerate_location_state_instructed(
    request: Request, project_id: str, loc_id: str, state_id: str,
    body: InstructedStateRegenRequest, project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.prompt_instructions import apply_asset_instruction
    project_dir, config, _state = project
    return await apply_asset_instruction(
        config=config, project_dir=project_dir, db=get_db(), user_id=user_id,
        project_id=project_id, asset_type="location", asset_id=loc_id,
        state_id=state_id, instruction=body.instruction, app=request.app,
    )


def _state_asset_path(project_dir, kind: str, entity_id: str, state_id: str):
    return (
        artifacts.character_state_ref_sheet_path(project_dir, entity_id, state_id)
        if kind == "character" else artifacts.location_state_plate_path(project_dir, entity_id, state_id)
    )


@router.get("/{kind}s/{entity_id}/states/{state_id}/versions")
def get_state_asset_versions(
    kind: str, entity_id: str, state_id: str, project=Depends(get_project),
):
    from novel_to_comic.panel_versions import list_asset_versions
    if kind not in {"character", "location"}:
        raise HTTPException(404, "Unknown state asset kind")
    project_dir, _config, _state = project
    path = _state_asset_path(project_dir, kind, entity_id, state_id)
    return {"entity_id": entity_id, "state_id": state_id, "versions": list_asset_versions(path, project_dir)}


@router.post("/{kind}s/{entity_id}/states/{state_id}/versions/{version}/restore")
def restore_state_asset_version(
    kind: str, entity_id: str, state_id: str, version: int,
    project=Depends(get_project),
):
    from novel_to_comic.panel_versions import list_asset_versions, restore_asset_version
    if kind not in {"character", "location"}:
        raise HTTPException(404, "Unknown state asset kind")
    project_dir, _config, _state = project
    path = _state_asset_path(project_dir, kind, entity_id, state_id)
    try:
        restore_asset_version(path, project_dir, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if kind == "character":
        from novel_to_comic.stages import s3_cast
        s3_cast._crop_sheet_to_poses(path)
    from novel_to_comic.state_assets import revalidate_state_asset_lineage
    parent = (
        artifacts.character_ref_sheet_path(project_dir, entity_id)
        if kind == "character" else artifacts.location_plate_path(project_dir, entity_id)
    )
    revalidate_state_asset_lineage(path, parent)
    return {"entity_id": entity_id, "state_id": state_id, "versions": list_asset_versions(path, project_dir)}


@router.get("/{kind}s/{entity_id}/states/{state_id}/metadata")
def get_state_asset_metadata(
    kind: str, entity_id: str, state_id: str, project=Depends(get_project),
):
    if kind not in {"character", "location"}:
        raise HTTPException(404, "Unknown state asset kind")
    project_dir, _config, _state = project
    path = _state_asset_path(project_dir, kind, entity_id, state_id)
    meta = artifacts.read_asset_meta(path)
    if not meta:
        raise HTTPException(404, "State asset metadata not found")
    return meta


@router.post("/regen-ref-instructed")
@limiter.limit(cost_limit)
async def regen_ref_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedRefRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project

    from novel_to_comic.prompt_instructions import apply_asset_instruction

    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="character",
        asset_id=body.char_id,
        instruction=body.instruction,
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
    project_dir, config, state = project

    from novel_to_comic.prompt_instructions import apply_asset_instruction

    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="location",
        asset_id=body.loc_id,
        instruction=body.instruction,
        app=request.app,
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

    _project_dir, config, _state = project
    return _enqueue_cast_asset_regen(
        request,
        project_id,
        user_id,
        project,
        kind="prop_ref_regen",
        asset_id_key="prop_id",
        asset_id=prop_id,
        label=f"Prop ref / {prop_id}",
        work=lambda: s3_cast.regenerate_prop_ref(config, _project_dir, prop_id),
        debit_description=f"Model call: regenerate prop ref {prop_id}",
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
    project_dir, config, state = project

    from novel_to_comic.prompt_instructions import apply_asset_instruction

    return await apply_asset_instruction(
        config=config,
        project_dir=project_dir,
        db=get_db(),
        user_id=user_id,
        project_id=project_id,
        asset_type="prop",
        asset_id=body.prop_id,
        instruction=body.instruction,
        app=request.app,
    )


@router.get("/generation-jobs")
def get_generation_jobs(
    request: Request,
    project_id: str,
    ids: list[str] | None = Query(None),
    user_id: str = Depends(get_current_user),
):
    pkey = project_key(user_id, project_id)
    jobs = [
        job
        for job in request.app.state.generation_jobs.values()
        if job.project_name == pkey and (ids is None or job.id in ids)
    ]
    jobs.sort(key=lambda job: job.sequence)
    return {"jobs": [generation_job_payload(request.app, job) for job in jobs]}


@router.post("/approve/{stage}")
def approve(
    stage: str,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    if stage == "draw":
        draw_error = _draw_ready_for_compose_error(project_dir)
        if draw_error:
            raise HTTPException(409, draw_error)
    try:
        approve_stage(state, stage)
    except ValueError as e:
        raise HTTPException(409, str(e))
    save_state(state, project_dir)
    capture_server_event(
        "stage_approved",
        user_id=user_id,
        project_id=project_id,
        properties={"stage": stage},
    )
    return {"status": "approved", "stage": stage}


@router.post("/reset/{stage}")
def reset_stage(
    stage: str,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Reset a failed stage back to pending so it can be re-run."""
    project_dir, config, state = project
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")

    stage_state = state.stages[stage]
    if stage_state.status != StageStatus.FAILED:
        raise HTTPException(
            409,
            f"Stage '{stage}' is not failed (status: {stage_state.status.value}). "
            "Only failed stages can be reset.",
        )

    state.stages[stage] = StageState()
    save_state(state, project_dir)
    db = get_db()
    release_stage_reservations(db, user_id, project_id, stage)
    return {
        "status": "reset",
        "stage": stage,
        "message": f"Stage '{stage}' has been reset to pending. You can now re-run it.",
    }


@router.post("/reset-stale")
def reset_stale(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Reset all stale RUNNING stages back to PENDING.

    A stage is stale when state.json shows RUNNING but no server-side process
    is actively tracking it — e.g. after a server restart or crash.
    Also releases any credit reservations held by those stages.
    """
    project_dir, config, state = project
    stale = get_stale_stages(state)
    if not stale:
        return {"status": "ok", "reset": [], "message": "No stale stages detected."}
    reset = reset_stale_stages(state)
    save_state(state, project_dir)
    db = get_db()
    for stage in reset:
        release_stage_reservations(db, user_id, project_id, stage)
    return {
        "status": "reset",
        "reset": reset,
        "message": f"Reset stale stages: {', '.join(reset)}",
    }


@router.get("/stage-error/{stage}")
def get_stage_error(stage: str, project_id: str, project=Depends(get_project)):
    """Get the error message from a failed stage."""
    project_dir, config, state = project
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")

    stage_state = state.stages[stage]
    if stage_state.status != StageStatus.FAILED:
        raise HTTPException(
            404, f"Stage '{stage}' is not failed (status: {stage_state.status.value})."
        )

    return {
        "stage": stage,
        "error": stage_state.error or "Unknown error",
        "items_failed": stage_state.items_failed,
    }
