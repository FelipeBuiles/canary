"""Pipeline execution, SSE streaming, and checkpoint approval."""

import asyncio
from datetime import UTC, datetime
import json
import logging
import shutil
import time
from typing import Optional
import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from novel_to_comic import artifacts
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.stages import REGISTRY
from novel_to_comic.prompt_instructions import (
    PromptInstructionError,
    apply_instruction_patch,
    asset_instruction_rewrite_system_prompt,
    asset_instruction_rewrite_user_content,
    instruction_rewrite_system_prompt,
    instruction_rewrite_user_content,
    parse_asset_instruction_patch,
    parse_instruction_patch,
    validate_user_instruction,
)
from novel_to_comic.prompting import generate_distilled_prompt
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
from novel_to_comic.ai import ai_request_context

from ..auth import get_current_user
from ..credits import (
    CreditEstimate,
    assert_sufficient_credits,
    debit_model_usage,
    estimate_stage_credit_breakdown,
    estimate_stage_credit_reservation,
    provider_usd_to_credits,
    release_reservation,
    release_stage_reservations,
    reserve_credits,
)
from ..db import get_db
from ..deps import get_project, project_key
from ..generation_jobs import (
    enqueue_generation_job,
    find_active_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)
from ..panel_acceptance import clear_panel_acceptance

router = APIRouter()
logger = logging.getLogger("canary.pipeline")


class InstructedPanelRegenRequest(BaseModel):
    scene_id: str = Field(min_length=1)
    panel_number: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedRefRegenRequest(BaseModel):
    char_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedPlateRegenRequest(BaseModel):
    loc_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class InstructedPropRegenRequest(BaseModel):
    prop_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


async def _run_stage(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
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
        await stage_obj.run(
            config,
            project_dir,
            state,
            on_event=lambda e: queue.put_nowait(e),
            **extra_kwargs,
        )
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
        message = str(exc)
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
    *,
    retry_failed: bool = False,
):
    """Reserve credits, run the stage, then settle or release the reservation."""
    db = get_db()
    try:
        reservation_credits = estimate_stage_credit_reservation(config, project_dir, state, stage)
        reservation_id, job_id = reserve_credits(db, user_id, project_id, stage, reservation_credits)
    except Exception as exc:
        # Insufficient credits or DB error — fail the stage so the UI reflects it.
        detail = getattr(exc, "detail", None)
        if isinstance(detail, str):
            message = detail
        elif isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("error") or exc)
        else:
            message = str(exc)
        fail_stage(state, stage, message)
        save_state(state, project_dir)
        event: dict[str, object] = {"type": "stage_fail", "stage": stage, "message": message}
        if isinstance(detail, dict) and detail.get("error") == "insufficient_credits":
            event["error_code"] = "insufficient_credits"
            event["balance_credits"] = detail.get("balance_credits")
            event["required_credits"] = detail.get("required_credits")
            event["shortfall_credits"] = detail.get("shortfall_credits")
        queue.put_nowait(event)
        return

    try:
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage=stage,
            job_id=job_id,
        ):
            await _run_stage(stage, config, project_dir, state, queue, retry_failed=retry_failed)

        s = state.stages[stage]
    finally:
        # Per-call debits land in the AI client as each API call returns
        # (see ai.client._settle_event_usage), so a crash mid-stage only loses
        # the in-flight request. Reservation just gets released either way.
        if reservation_id:
            release_reservation(db, reservation_id)

    # Auto-chain: if the stage completed (not awaiting_review, not failed),
    # automatically run the next stages in the chain.
    if s.status == StageStatus.COMPLETE and stage in STAGE_AUTO_CHAIN:
        for next_stage in STAGE_AUTO_CHAIN[stage]:
            next_s = state.stages[next_stage]
            if next_s.status != StageStatus.PENDING:
                continue
            await _run_stage_with_credits(next_stage, config, project_dir, state, queue, user_id, project_id)
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
    breakdown = estimate_stage_credit_breakdown(config, project_dir, state, chain[0])
    for chained in chain[1:]:
        extra = estimate_stage_credit_breakdown(config, project_dir, state, chained)
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
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Return the estimated credit cost to regenerate one panel image."""
    from novel_to_comic.stages.s7_draw import estimate_panel_image_cost_usd
    from ..credits import reservation_buffer, stage_cost_confidence
    project_dir, config, _state = project
    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")
    cost_usd = estimate_panel_image_cost_usd(config, project_dir, prompt_path)
    estimate_credits = max(1, provider_usd_to_credits(cost_usd)) if cost_usd > 0 else 1
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "estimate_credits": estimate_credits,
        "reserved_credits": None,
        "reservation_multiplier": reservation_buffer(),
        "confidence": stage_cost_confidence("draw"),
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
        stage, config, project_dir, state, queue, user_id, project_id, retry_failed=retry_failed
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
    job = _run_stage_with_credits("extract", config, project_dir, state, queue, user_id, project_id)
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


@router.post("/regen")
async def regen_panel(
    request: Request,
    project_id: str,
    scene_id: str = Query(...),
    panel_number: int = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    running = request.app.state.running_tasks
    existing = running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")
    planned_panel_id = None
    try:
        planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
    except Exception:
        planned_panel_id = None

    # Pre-check credits (panel regen has no upfront reservation, so we have to
    # gate on the estimate ourselves to surface a buy-credits prompt cleanly).
    from novel_to_comic.stages.s7_draw import estimate_panel_image_cost_usd

    panel_cost_usd = estimate_panel_image_cost_usd(config, project_dir, prompt_path)
    panel_estimate_credits = max(1, provider_usd_to_credits(panel_cost_usd)) if panel_cost_usd > 0 else 1
    assert_sufficient_credits(get_db(), user_id, panel_estimate_credits, action="panel_regen")

    regen_job_id = str(uuid_lib.uuid4())

    async def _runner() -> None:
        from novel_to_comic.stages import s7_draw
        clear_panel_acceptance(project_dir, scene_id, panel_number)
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="draw",
            job_id=regen_job_id,
        ):
            result = await s7_draw.regenerate_panel_image(
                config,
                project_dir,
                scene_id,
                panel_number,
            )
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="draw",
                description=f"Model call: regenerate panel {scene_id}/{panel_number:03d}",
                job_id=regen_job_id,
            )

    existing = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="panel_regen",
        payload={"scene_id": scene_id, "panel_number": panel_number},
    )
    if existing:
        return {
            "status": "queued",
            "job": generation_job_payload(request.app, existing),
            "scene_id": scene_id,
            "panel_number": panel_number,
            "planned_panel_id": planned_panel_id,
        }

    prune_finished_generation_jobs(request.app)
    clear_panel_acceptance(project_dir, scene_id, panel_number)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="panel_regen",
        label=f"{scene_id} / panel {panel_number:03d}",
        payload={"scene_id": scene_id, "panel_number": panel_number},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
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
    scene_id = body.scene_id
    panel_number = body.panel_number

    running = request.app.state.running_tasks
    existing_stage = running.get(pkey)
    if existing_stage and not existing_stage.done():
        raise HTTPException(409, "A stage is already running for this project")

    existing_regen = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="panel_regen",
        payload={"scene_id": scene_id, "panel_number": panel_number},
    )
    if existing_regen:
        raise HTTPException(409, "A regeneration is already queued or running for this panel")

    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")

    try:
        instruction = validate_user_instruction(body.instruction)
    except PromptInstructionError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Pre-check credits before the prompt-rewrite call and the eventual image regen.
    from novel_to_comic.stages.s7_draw import estimate_panel_image_cost_usd

    panel_cost_usd = estimate_panel_image_cost_usd(config, project_dir, prompt_path)
    panel_estimate_credits = max(1, provider_usd_to_credits(panel_cost_usd)) if panel_cost_usd > 0 else 1
    assert_sufficient_credits(get_db(), user_id, panel_estimate_credits, action="panel_regen")

    prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    from novel_to_comic.clients import text

    instructed_job_id = str(uuid_lib.uuid4())
    try:
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="draw",
            job_id=instructed_job_id,
        ):
            rewrite = await text.generate_json(
                config=config,
                model=config.effective_prompt_model(),
                system_prompt=instruction_rewrite_system_prompt(),
                user_content=instruction_rewrite_user_content(instruction, prompt),
                temperature=0.2,
                max_output_tokens=1200,
                feature="draw.panel_instruction_rewrite",
            )
        patch = parse_instruction_patch(rewrite.value)
        updated_prompt = apply_instruction_patch(prompt, patch)
        updated_prompt.distilled_prompt = generate_distilled_prompt(updated_prompt)
    except PromptInstructionError as exc:
        logger.warning(
            "Panel instruction rewrite could not be applied project=%s scene=%s panel=%s reason=%s rewrite=%s",
            project_dir.name,
            scene_id,
            panel_number,
            exc,
            json.dumps(rewrite.value, ensure_ascii=False)[:1000] if "rewrite" in locals() else None,
        )
        raise HTTPException(400, f"Prompt rewrite could not be applied: {exc}") from exc
    except Exception as exc:
        logger.exception(
            "Panel instruction rewrite failed project=%s scene=%s panel=%s",
            project_dir.name,
            scene_id,
            panel_number,
        )
        raise HTTPException(502, f"Could not rewrite the panel prompt: {exc}") from exc

    db = get_db()
    if rewrite.usage:
        debit_model_usage(
            db,
            user_id,
            project_id,
            rewrite.usage,
            stage="draw",
            description=f"Model call: rewrite panel prompt {scene_id}/{panel_number:03d}",
            job_id=instructed_job_id,
        )

    prompt_path.write_text(updated_prompt.model_dump_json(indent=2))
    clear_panel_acceptance(project_dir, scene_id, panel_number)
    _append_instruction_log(
        project_dir,
        scene_id,
        panel_number,
        instruction=instruction,
        patch=patch.model_dump(),
        prompt=updated_prompt,
    )

    async def _runner() -> None:
        from novel_to_comic.stages import s7_draw

        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="draw",
            job_id=instructed_job_id,
        ):
            result = await s7_draw.regenerate_panel_image(
                config,
                project_dir,
                scene_id,
                panel_number,
            )
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="draw",
                description=f"Model call: regenerate instructed panel {scene_id}/{panel_number:03d}",
                job_id=instructed_job_id,
            )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="panel_regen",
        label=f"{scene_id} / panel {panel_number:03d}",
        payload={"scene_id": scene_id, "panel_number": panel_number},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "instruction_status": "accepted",
        "patch_summary": patch.message,
        "job": generation_job_payload(request.app, job),
        "scene_id": scene_id,
        "panel_number": panel_number,
        "planned_panel_id": updated_prompt.planned_panel_id,
        "prompt": updated_prompt.model_dump(),
    }


@router.post("/regen-ref")
async def regen_ref(
    request: Request,
    project_id: str,
    char_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    char_ref_job_id = str(uuid_lib.uuid4())

    async def _runner() -> None:
        from novel_to_comic.stages import s3_cast
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=char_ref_job_id,
        ):
            result = await s3_cast.regenerate_character_ref(
                config,
                project_dir,
                char_id,
            )
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="cast",
                description=f"Model call: regenerate character ref {char_id}",
                job_id=char_ref_job_id,
            )

    existing = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="character_ref_regen",
        payload={"char_id": char_id},
    )
    if existing:
        return {
            "status": "queued",
            "job": generation_job_payload(request.app, existing),
            "char_id": char_id,
        }

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="character_ref_regen",
        label=f"Character ref / {char_id}",
        payload={"char_id": char_id},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "char_id": char_id,
    }


@router.post("/regen-plate")
async def regen_plate(
    request: Request,
    project_id: str,
    loc_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)
    plate_job_id = str(uuid_lib.uuid4())

    async def _runner() -> None:
        from novel_to_comic.stages import s3_cast
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=plate_job_id,
        ):
            result = await s3_cast.regenerate_location_plate(
                config,
                project_dir,
                loc_id,
            )
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="cast",
                description=f"Model call: regenerate location plate {loc_id}",
                job_id=plate_job_id,
            )

    existing = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="location_plate_regen",
        payload={"loc_id": loc_id},
    )
    if existing:
        return {
            "status": "queued",
            "job": generation_job_payload(request.app, existing),
            "loc_id": loc_id,
        }

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="location_plate_regen",
        label=f"Location plate / {loc_id}",
        payload={"loc_id": loc_id},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "loc_id": loc_id,
    }


@router.post("/regen-ref-instructed")
async def regen_ref_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedRefRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)
    char_id = body.char_id

    existing_regen = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="character_ref_regen",
        payload={"char_id": char_id},
    )
    if existing_regen:
        raise HTTPException(409, "A regeneration is already queued or running for this character")

    bible = artifacts.read_story_bible(project_dir)
    char = next((c for c in bible.characters if c.id == char_id), None)
    if char is None:
        raise HTTPException(404, f"Character not found: {char_id}")

    try:
        instruction = validate_user_instruction(body.instruction)
    except PromptInstructionError as exc:
        raise HTTPException(400, str(exc)) from exc

    instructions_path = artifacts.character_ref_instructions_path(project_dir, char_id)
    prior_addendum = artifacts.read_active_addendum(instructions_path)

    rewrite_context = {
        "character_name": char.name,
        "visual_anchor": char.visual_anchor,
        "default_outfit": char.default_outfit,
        "distinguishing_features": char.distinguishing_features,
        "prior_addendum": prior_addendum,
    }

    from novel_to_comic.clients import text

    job_id = str(uuid_lib.uuid4())
    rewrite = None
    try:
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=job_id,
        ):
            rewrite = await text.generate_json(
                config=config,
                model=config.effective_prompt_model(),
                system_prompt=asset_instruction_rewrite_system_prompt("character_ref"),
                user_content=asset_instruction_rewrite_user_content(
                    instruction, "character_ref", rewrite_context
                ),
                temperature=0.2,
                max_output_tokens=900,
                feature="cast.character_ref_instruction_rewrite",
            )
        patch = parse_asset_instruction_patch(rewrite.value)
    except PromptInstructionError as exc:
        logger.warning(
            "Character ref instruction rewrite could not be applied project=%s char=%s reason=%s rewrite=%s",
            project_dir.name,
            char_id,
            exc,
            json.dumps(rewrite.value, ensure_ascii=False)[:1000] if rewrite is not None else None,
        )
        raise HTTPException(400, f"Prompt rewrite could not be applied: {exc}") from exc
    except Exception as exc:
        logger.exception(
            "Character ref instruction rewrite failed project=%s char=%s",
            project_dir.name,
            char_id,
        )
        raise HTTPException(502, f"Could not rewrite the character prompt: {exc}") from exc

    if rewrite.usage:
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            rewrite.usage,
            stage="cast",
            description=f"Model call: rewrite character ref prompt {char_id}",
            job_id=job_id,
        )

    artifacts.append_instruction_log_entry(
        instructions_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "instruction": instruction,
            "patch": patch.model_dump(),
        },
    )

    async def _runner() -> None:
        from novel_to_comic.stages import s3_cast
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=job_id,
        ):
            result = await s3_cast.regenerate_character_ref(config, project_dir, char_id)
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="cast",
                description=f"Model call: regenerate instructed character ref {char_id}",
                job_id=job_id,
            )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="character_ref_regen",
        label=f"Character ref / {char_id}",
        payload={"char_id": char_id},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "instruction_status": "accepted",
        "patch_summary": patch.message,
        "addendum": patch.addendum,
        "job": generation_job_payload(request.app, job),
        "char_id": char_id,
    }


@router.post("/regen-plate-instructed")
async def regen_plate_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPlateRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)
    loc_id = body.loc_id

    existing_regen = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="location_plate_regen",
        payload={"loc_id": loc_id},
    )
    if existing_regen:
        raise HTTPException(409, "A regeneration is already queued or running for this location")

    bible = artifacts.read_story_bible(project_dir)
    loc = next((candidate for candidate in bible.locations if candidate.id == loc_id), None)
    if loc is None:
        raise HTTPException(404, f"Location not found: {loc_id}")

    try:
        instruction = validate_user_instruction(body.instruction)
    except PromptInstructionError as exc:
        raise HTTPException(400, str(exc)) from exc

    instructions_path = artifacts.location_plate_instructions_path(project_dir, loc_id)
    prior_addendum = artifacts.read_active_addendum(instructions_path)

    rewrite_context = {
        "location_name": loc.name,
        "visual_anchor": loc.visual_anchor,
        "time_of_day": loc.time_of_day,
        "mood": loc.mood,
        "prior_addendum": prior_addendum,
    }

    from novel_to_comic.clients import text

    job_id = str(uuid_lib.uuid4())
    rewrite = None
    try:
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=job_id,
        ):
            rewrite = await text.generate_json(
                config=config,
                model=config.effective_prompt_model(),
                system_prompt=asset_instruction_rewrite_system_prompt("location_plate"),
                user_content=asset_instruction_rewrite_user_content(
                    instruction, "location_plate", rewrite_context
                ),
                temperature=0.2,
                max_output_tokens=900,
                feature="cast.location_plate_instruction_rewrite",
            )
        patch = parse_asset_instruction_patch(rewrite.value)
    except PromptInstructionError as exc:
        logger.warning(
            "Location plate instruction rewrite could not be applied project=%s loc=%s reason=%s rewrite=%s",
            project_dir.name,
            loc_id,
            exc,
            json.dumps(rewrite.value, ensure_ascii=False)[:1000] if rewrite is not None else None,
        )
        raise HTTPException(400, f"Prompt rewrite could not be applied: {exc}") from exc
    except Exception as exc:
        logger.exception(
            "Location plate instruction rewrite failed project=%s loc=%s",
            project_dir.name,
            loc_id,
        )
        raise HTTPException(502, f"Could not rewrite the location prompt: {exc}") from exc

    if rewrite.usage:
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            rewrite.usage,
            stage="cast",
            description=f"Model call: rewrite location plate prompt {loc_id}",
            job_id=job_id,
        )

    artifacts.append_instruction_log_entry(
        instructions_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "instruction": instruction,
            "patch": patch.model_dump(),
        },
    )

    async def _runner() -> None:
        from novel_to_comic.stages import s3_cast
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=job_id,
        ):
            result = await s3_cast.regenerate_location_plate(config, project_dir, loc_id)
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="cast",
                description=f"Model call: regenerate instructed location plate {loc_id}",
                job_id=job_id,
            )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="location_plate_regen",
        label=f"Location plate / {loc_id}",
        payload={"loc_id": loc_id},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "instruction_status": "accepted",
        "patch_summary": patch.message,
        "addendum": patch.addendum,
        "job": generation_job_payload(request.app, job),
        "loc_id": loc_id,
    }


@router.post("/regen-prop")
async def regen_prop(
    request: Request,
    project_id: str,
    prop_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)
    prop_job_id = str(uuid_lib.uuid4())

    async def _runner() -> None:
        from novel_to_comic.stages import s3_cast
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=prop_job_id,
        ):
            result = await s3_cast.regenerate_prop_ref(
                config,
                project_dir,
                prop_id,
            )
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="cast",
                description=f"Model call: regenerate prop ref {prop_id}",
                job_id=prop_job_id,
            )

    existing = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="prop_ref_regen",
        payload={"prop_id": prop_id},
    )
    if existing:
        return {
            "status": "queued",
            "job": generation_job_payload(request.app, existing),
            "prop_id": prop_id,
        }

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="prop_ref_regen",
        label=f"Prop ref / {prop_id}",
        payload={"prop_id": prop_id},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(request.app, job),
        "prop_id": prop_id,
    }


@router.post("/regen-prop-instructed")
async def regen_prop_with_instruction(
    request: Request,
    project_id: str,
    body: InstructedPropRegenRequest,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)
    prop_id = body.prop_id

    existing_regen = find_active_generation_job(
        request.app,
        project_name=pkey,
        kind="prop_ref_regen",
        payload={"prop_id": prop_id},
    )
    if existing_regen:
        raise HTTPException(409, "A regeneration is already queued or running for this prop")

    bible = artifacts.read_story_bible(project_dir)
    prop = next((candidate for candidate in bible.props if candidate.id == prop_id), None)
    if prop is None:
        raise HTTPException(404, f"Prop not found: {prop_id}")

    try:
        instruction = validate_user_instruction(body.instruction)
    except PromptInstructionError as exc:
        raise HTTPException(400, str(exc)) from exc

    instructions_path = artifacts.prop_ref_instructions_path(project_dir, prop_id)
    prior_addendum = artifacts.read_active_addendum(instructions_path)

    rewrite_context = {
        "prop_name": prop.name,
        "visual_anchor": prop.visual_anchor,
        "prior_addendum": prior_addendum,
    }

    from novel_to_comic.clients import text

    job_id = str(uuid_lib.uuid4())
    rewrite = None
    try:
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=job_id,
        ):
            rewrite = await text.generate_json(
                config=config,
                model=config.effective_prompt_model(),
                system_prompt=asset_instruction_rewrite_system_prompt("prop_ref"),
                user_content=asset_instruction_rewrite_user_content(
                    instruction, "prop_ref", rewrite_context
                ),
                temperature=0.2,
                max_output_tokens=900,
                feature="cast.prop_ref_instruction_rewrite",
            )
        patch = parse_asset_instruction_patch(rewrite.value)
    except PromptInstructionError as exc:
        logger.warning(
            "Prop ref instruction rewrite could not be applied project=%s prop=%s reason=%s rewrite=%s",
            project_dir.name,
            prop_id,
            exc,
            json.dumps(rewrite.value, ensure_ascii=False)[:1000] if rewrite is not None else None,
        )
        raise HTTPException(400, f"Prompt rewrite could not be applied: {exc}") from exc
    except Exception as exc:
        logger.exception(
            "Prop ref instruction rewrite failed project=%s prop=%s",
            project_dir.name,
            prop_id,
        )
        raise HTTPException(502, f"Could not rewrite the prop prompt: {exc}") from exc

    if rewrite.usage:
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            rewrite.usage,
            stage="cast",
            description=f"Model call: rewrite prop ref prompt {prop_id}",
            job_id=job_id,
        )

    artifacts.append_instruction_log_entry(
        instructions_path,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "instruction": instruction,
            "patch": patch.model_dump(),
        },
    )

    async def _runner() -> None:
        from novel_to_comic.stages import s3_cast
        with ai_request_context(
            user_id=user_id,
            project_id=project_id,
            project_name=project_dir.name,
            workspace_id=str(project_dir.parent),
            stage="cast",
            job_id=job_id,
        ):
            result = await s3_cast.regenerate_prop_ref(config, project_dir, prop_id)
        if result.usage:
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                stage="cast",
                description=f"Model call: regenerate instructed prop ref {prop_id}",
                job_id=job_id,
            )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="prop_ref_regen",
        label=f"Prop ref / {prop_id}",
        payload={"prop_id": prop_id},
        runner=_runner,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "instruction_status": "accepted",
        "patch_summary": patch.message,
        "addendum": patch.addendum,
        "job": generation_job_payload(request.app, job),
        "prop_id": prop_id,
    }


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
