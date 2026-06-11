"""Pipeline execution, SSE streaming, and checkpoint approval."""

import asyncio
from datetime import UTC, datetime
import json
import logging
import shutil
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from novel_to_comic import artifacts
from novel_to_comic.config import Config, config_for_image_model_alias
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
)
from ..db import get_db
from ..deps import get_project, project_key
from ..credited_job import (
    CreditReservationDenied,
    enqueue_credited_job,
    run_credited_stage,
)
from ..generation_jobs import (
    generation_job_payload,
    generation_semaphore_for_config,
)
from ..panel_acceptance import clear_panel_acceptance
from ..panel_flags import clear_panel_flag

router = APIRouter()
logger = logging.getLogger("canary.pipeline")


def _panel_regen_config_for_alias(config: Config, image_model_alias: str | None) -> Config:
    try:
        return config_for_image_model_alias(config, image_model_alias)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class InstructedPanelRegenRequest(BaseModel):
    scene_id: str = Field(min_length=1)
    panel_number: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=500)
    image_model_alias: str | None = None


class InstructedRefRegenRequest(BaseModel):
    char_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedPlateRegenRequest(BaseModel):
    loc_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedPropRegenRequest(BaseModel):
    prop_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


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
            in_flight_map.setdefault(pkey, []).append({
                "scene_id": event["scene_id"],
                "panel_number": event["panel_number"],
                "started_at": event["started_at"],
            })
        elif evt_type == "panel_done":
            existing = in_flight_map.get(pkey, [])
            in_flight_map[pkey] = [
                e for e in existing
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
            stage, state, project_dir,
            on_event=_wrap_on_event(queue, app_state, pkey),
        )
        await stage_obj.run(config, project_dir, ctx, **extra_kwargs)
        elapsed = time.perf_counter() - started
        status = state.stages[stage].status.value
        status_color = "green" if status in {"complete", "awaiting_review"} else "yellow"
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
        message = clean_exception_message(exc)
        # StageRuntime.execute() already called fail_stage + save_state + emitted stage_fail.
        # This catch handles the case where a stage raises before entering execute().
        if state.stages[stage].status.value not in ("failed",):
            fail_stage(state, stage, message)
            save_state(state, project_dir)
            queue.put_nowait({"type": "stage_fail", "stage": stage, "message": message})
        elapsed = time.perf_counter() - started
        logger.exception(
            "[bold red]Stage failed[/] project=[white]%s[/] stage=[bold]%s[/] "
            "elapsed=[bold]%.1fs[/] error=%s",
            project_dir.name,
            stage,
            elapsed,
            message,
        )



# Stages that auto-chain: when the first stage completes, the rest run automatically.
# The chain stops at the first failure or awaiting_review checkpoint.
STAGE_AUTO_CHAIN: dict[str, list[str]] = {
    "adapt": ["plan", "storyboard", "direct"],
    "plan": ["storyboard", "direct"],
    "storyboard": ["direct"],
}


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
    retry_failed: bool = False,
):
    """Run the stage behind a credit guarantee, then auto-chain."""
    try:
        await run_credited_stage(
            user_id=user_id,
            project_id=project_id,
            project_dir=project_dir,
            config=config,
            state=state,
            stage=stage,
            run=lambda: _run_stage(
                stage, config, project_dir, state, queue, app_state, pkey,
                retry_failed=retry_failed,
            ),
        )
    except CreditReservationDenied as denied:
        # Insufficient credits or DB error — fail the stage so the UI reflects it.
        fail_stage(state, stage, denied.message)
        save_state(state, project_dir)
        event: dict[str, object] = {"type": "stage_fail", "stage": stage, "message": denied.message}
        if denied.detail and denied.detail.get("error") == "insufficient_credits":
            event["error_code"] = "insufficient_credits"
            event["balance_credits"] = denied.detail.get("balance_credits")
            event["required_credits"] = denied.detail.get("required_credits")
            event["shortfall_credits"] = denied.detail.get("shortfall_credits")
        queue.put_nowait(event)
        return

    s = state.stages[stage]

    # Auto-chain: if the stage completed (not awaiting_review, not failed),
    # automatically run the next stages in the chain.
    if s.status == StageStatus.COMPLETE and stage in STAGE_AUTO_CHAIN:
        for next_stage in STAGE_AUTO_CHAIN[stage]:
            next_s = state.stages[next_stage]
            if next_s.status != StageStatus.PENDING:
                continue
            await _run_stage_with_credits(
                next_stage, config, project_dir, state, queue,
                user_id, project_id, app_state, pkey,
            )
            # Stop if the chained stage failed or hit a review checkpoint
            if state.stages[next_stage].status in (StageStatus.FAILED, StageStatus.AWAITING_REVIEW):
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
    log_path = artifacts.panel_prompt_instructions_path(project_dir, scene_id, panel_number)
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
    breakdown = UnifiedCostResolver.estimate_stage_cost(config, project_dir, state, chain[0])
    for chained in chain[1:]:
        extra = UnifiedCostResolver.estimate_stage_cost(config, project_dir, state, chained)
        breakdown = CreditEstimate(
            estimate_credits=breakdown["estimate_credits"] + extra["estimate_credits"],
            reserved_credits=(breakdown["reserved_credits"] or 0) + (extra["reserved_credits"] or 0),
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
    project_dir, config, _state = project
    breakdown = UnifiedCostResolver.estimate_panel_regen_cost(
        config, project_dir, scene_id, panel_number, image_model_alias
    )
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        **breakdown,
    }


@router.post("/run")
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
        raise HTTPException(409, "A style operation is already running for this project")

    if stage == "compose":
        draw_error = _draw_ready_for_compose_error(project_dir)
        if draw_error:
            raise HTTPException(409, draw_error)

    if not stage:
        raise HTTPException(400, "stage parameter is required")

    # Gate: post-style stages require a style to have been selected
    _POST_STYLE_STAGES = {"cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"}
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
    required_credits = estimate_stage_credit_reservation(config, project_dir, state, stage)
    assert_sufficient_credits(db, user_id, required_credits, stage=stage)

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue

    job = _run_stage_with_credits(
        stage, config, project_dir, state, queue, user_id, project_id,
        request.app.state, pkey, retry_failed=retry_failed,
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
        raise HTTPException(409, "A style operation is already running for this project")

    # Keep behavior aligned with /run?stage=extract&rerun=1:
    # reset extract + all downstream stage state, and clear downstream outputs.
    _reset_stage_and_downstream(state, "extract")
    _clear_outputs_for_rerun(project_dir, "extract")
    save_state(state, project_dir)

    db = get_db()
    required_credits = estimate_stage_credit_reservation(config, project_dir, state, "extract")
    assert_sufficient_credits(db, user_id, required_credits, stage="extract")

    # Run extract stage via SSE pipeline (same pattern as POST /run?stage=extract)
    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue
    job = _run_stage_with_credits(
        "extract", config, project_dir, state, queue, user_id, project_id,
        request.app.state, pkey,
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
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        asset_id_key: asset_id,
    }


@router.post("/regen")
async def regen_panel(
    request: Request,
    project_id: str,
    scene_id: str = Query(...),
    panel_number: int = Query(...),
    image_model_alias: str | None = Query(None),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    from novel_to_comic.stages import s7_draw

    project_dir, config, state = project
    regen_config = _panel_regen_config_for_alias(config, image_model_alias)
    pkey = project_key(user_id, project_id)

    running = request.app.state.running_tasks
    existing_stage = running.get(pkey)
    if existing_stage and not existing_stage.done():
        raise HTTPException(409, "A stage is already running for this project")

    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")
    planned_panel_id = None
    try:
        planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
    except Exception:
        planned_panel_id = None

    panel_estimate = UnifiedCostResolver.estimate_panel_regen_cost(
        config, project_dir, scene_id, panel_number, image_model_alias
    )
    panel_estimate_credits = panel_estimate["estimate_credits"]

    async def _work():
        clear_panel_acceptance(project_dir, scene_id, panel_number)
        clear_panel_flag(project_dir, scene_id, panel_number)
        return await s7_draw.regenerate_panel_image(regen_config, project_dir, scene_id, panel_number)

    job, created = enqueue_credited_job(
        request.app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        stage="draw",
        kind="panel_regen",
        label=f"{scene_id} / panel {panel_number:03d}",
        payload={"scene_id": scene_id, "panel_number": panel_number},
        work=_work,
        debit_description=f"Model call: regenerate panel {scene_id}/{panel_number:03d}",
        semaphore=generation_semaphore_for_config(request.app, regen_config),
        estimate_credits=panel_estimate_credits,
    )
    if created:
        # Immediately clear acceptance so the UI shows the panel as pending
        # before the job starts running (the runner clears it again for safety).
        clear_panel_acceptance(project_dir, scene_id, panel_number)
        clear_panel_flag(project_dir, scene_id, panel_number)
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "scene_id": scene_id,
        "panel_number": panel_number,
        "planned_panel_id": planned_panel_id,
    }


@router.post("/regen-instructed")
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

    return await apply_asset_instruction(
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


@router.post("/regen-ref")
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
        request, project_id, user_id, project,
        kind="character_ref_regen",
        asset_id_key="char_id",
        asset_id=char_id,
        label=f"Character ref / {char_id}",
        work=lambda: s3_cast.regenerate_character_ref(config, _project_dir, char_id),
        debit_description=f"Model call: regenerate character ref {char_id}",
    )


@router.post("/regen-plate")
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
        request, project_id, user_id, project,
        kind="location_plate_regen",
        asset_id_key="loc_id",
        asset_id=loc_id,
        label=f"Location plate / {loc_id}",
        work=lambda: s3_cast.regenerate_location_plate(config, _project_dir, loc_id),
        debit_description=f"Model call: regenerate location plate {loc_id}",
    )


@router.post("/regen-ref-instructed")
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
        request, project_id, user_id, project,
        kind="prop_ref_regen",
        asset_id_key="prop_id",
        asset_id=prop_id,
        label=f"Prop ref / {prop_id}",
        work=lambda: s3_cast.regenerate_prop_ref(config, _project_dir, prop_id),
        debit_description=f"Model call: regenerate prop ref {prop_id}",
    )


@router.post("/regen-prop-instructed")
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
def approve(stage: str, project_id: str, project=Depends(get_project)):
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
            "Only failed stages can be reset."
        )

    state.stages[stage] = StageState()
    save_state(state, project_dir)
    db = get_db()
    release_stage_reservations(db, user_id, project_id, stage)
    return {
        "status": "reset",
        "stage": stage,
        "message": f"Stage '{stage}' has been reset to pending. You can now re-run it."
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
            404,
            f"Stage '{stage}' is not failed (status: {stage_state.status.value})."
        )

    return {
        "stage": stage,
        "error": stage_state.error or "Unknown error",
        "items_failed": stage_state.items_failed,
    }
