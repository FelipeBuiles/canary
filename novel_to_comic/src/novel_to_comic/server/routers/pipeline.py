"""Pipeline execution, SSE streaming, and checkpoint approval."""

import asyncio
import json
import logging
import shutil
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_to_comic.state import (
    STAGE_NAMES,
    StageState,
    StageStatus,
    approve_stage,
    fail_stage,
    get_stale_stages,
    is_stale,
    reset_stale_stages,
    save_state,
)
from novel_to_comic.usage import UsageRecord

from ..auth import get_current_user
from ..credits import (
    debit_model_usage,
    estimate_stage_credit_reservation,
    get_project_id,
    release_reservation,
    release_stage_reservations,
    reserve_credits,
)
from ..db import get_db
from ..deps import get_project, project_key
from .styles import is_style_selected
from ..generation_jobs import (
    enqueue_generation_job,
    find_active_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)

router = APIRouter()
logger = logging.getLogger("canary.pipeline")

_RERUN_CLEAN_PATHS: dict[str, tuple[str, ...]] = {
    "extract": ("story_bible.json", "scenes", "refs", "plates", "adapt", "plan", "storyboard", "direct", "draw", "compose", "exports"),
    "cast": ("refs", "plates", "adapt", "plan", "storyboard", "direct", "draw", "compose", "exports"),
    "adapt": ("adapt", "plan", "storyboard", "direct", "draw", "compose", "exports"),
    "plan": ("plan", "storyboard", "direct", "draw", "compose", "exports"),
    "storyboard": ("storyboard", "direct", "draw", "compose", "exports"),
    "direct": ("direct", "draw", "compose", "exports"),
    "draw": ("draw", "compose", "exports"),
    "compose": ("compose", "exports"),
}


def _stage_runner(stage: str, config, project_dir, state):
    """Import and return the async run() coroutine for a given stage."""
    from novel_to_comic.stages import (
        s1_extract, s2_index, s3_screenplay,
        s4_layout_plan, s4_panels, s5_prompts, s6_generate, s7_assemble,
    )
    runners = {
        "extract":    lambda on_event: s1_extract.run(config, project_dir, state, on_event=on_event),
        "cast":       lambda on_event: s2_index.run(config, project_dir, state, on_event=on_event),
        "adapt":      lambda on_event: s3_screenplay.run(config, project_dir, state, on_event=on_event),
        "plan":       lambda on_event: s4_layout_plan.run(config, project_dir, state, on_event=on_event),
        "storyboard": lambda on_event: s4_panels.run(config, project_dir, state, on_event=on_event),
        "direct":     lambda on_event: s5_prompts.run(config, project_dir, state, on_event=on_event),
        "draw":       lambda on_event: s6_generate.run(config, project_dir, state, on_event=on_event),
        "compose":    lambda on_event: s7_assemble.run(config, project_dir, state, on_event=on_event),
    }
    return runners.get(stage)


async def _run_stage(stage: str, config, project_dir, state, queue: asyncio.Queue):
    """Execute a single stage, feeding events into the queue."""
    started = time.perf_counter()
    logger.info(
        "[bold cyan]Stage start[/] project=[white]%s[/] stage=[bold]%s[/]",
        project_dir.name,
        stage,
    )
    try:
        runner = _stage_runner(stage, config, project_dir, state)
        if not runner:
            raise ValueError(f"Unknown stage: {stage}")
        await runner(on_event=lambda e: queue.put_nowait(e))
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


# Primary output artifact for each stage — used to detect stale "complete" state.
_STAGE_OUTPUTS: dict[str, str] = {
    "extract": "story_bible.json",
    "cast": "refs",
    "adapt": "screenplays",
    "plan": "plan",
    "storyboard": "storyboard",
    "direct": "direct",
    "draw": "draw",
    "compose": "exports",
}


async def _run_stage_with_credits(
    stage: str,
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    user_id: str,
    project_id: str | None,
):
    """Reserve credits, run the stage, then settle or release the reservation."""
    db = get_db()
    try:
        reservation_credits = estimate_stage_credit_reservation(config, project_dir, state, stage)
        reservation_id = reserve_credits(db, user_id, project_id, stage, reservation_credits)
    except Exception as exc:
        # Insufficient credits or DB error — fail the stage so the UI reflects it.
        message = getattr(exc, "detail", str(exc))
        fail_stage(state, stage, message)
        save_state(state, project_dir)
        queue.put_nowait({"type": "stage_fail", "stage": stage, "message": message})
        return

    await _run_stage(stage, config, project_dir, state, queue)

    s = state.stages[stage]
    for usage in s.usage_log:
        debit_model_usage(
            db,
            user_id,
            project_id,
            UsageRecord.model_validate(usage),
            stage=stage,
            description=f"Model call: {stage}",
        )
    if reservation_id:
        release_reservation(db, reservation_id)


async def _run_full_pipeline(
    config,
    project_dir,
    state,
    queue: asyncio.Queue,
    user_id: str,
    project_id: str | None,
):
    """Run all stages in order, stopping at checkpoints or failures."""
    for stage in STAGE_NAMES:
        s = state.stages[stage]
        if s.status.value in ("complete",):
            # Verify the stage's output actually exists — if it was falsely
            # marked complete (e.g. a bug that has since been fixed), auto-recover.
            output = _STAGE_OUTPUTS.get(stage)
            if output and not (project_dir / output).exists():
                logger.warning(
                    "Stage %s marked complete but output %s missing — resetting and rerunning",
                    stage, output,
                )
                _reset_stage_and_downstream(state, stage)
                _clear_outputs_for_rerun(project_dir, stage)
                save_state(state, project_dir)
                # Fall through to run this stage
            else:
                continue
        if s.status == StageStatus.AWAITING_REVIEW:
            queue.put_nowait({
                "type": "log", "stage": stage, "level": "warn",
                "message": f"Stage '{stage}' is awaiting review — stopping.",
            })
            break

        await _run_stage_with_credits(stage, config, project_dir, state, queue, user_id, project_id)

        # Stop if stage failed or hit a checkpoint
        s = state.stages[stage]
        if s.status == StageStatus.FAILED:
            break
        if s.status == StageStatus.AWAITING_REVIEW:
            queue.put_nowait({
                "type": "log", "stage": stage, "level": "info",
                "message": f"Stage '{stage}' awaiting review.",
            })
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
    for rel_path in _RERUN_CLEAN_PATHS.get(stage, ()):
        path = project_dir / rel_path
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


@router.get("/estimate")
async def estimate_stage_cost(
    project_name: str,
    stage: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Return the estimated credit reservation for running a stage."""
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    project_dir, config, state = project
    credits = estimate_stage_credit_reservation(config, project_dir, state, stage)
    return {"stage": stage, "credits": credits}


@router.post("/run")
async def run_pipeline(
    request: Request,
    project_name: str,
    stage: Optional[str] = Query(None),
    rerun: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    if stage and stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")
    if rerun and not stage:
        raise HTTPException(400, "rerun=true requires a specific stage")

    # Concurrency guard
    running = request.app.state.running_tasks
    existing = running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    # Style gate: extract must be done, target includes post-extract stage,
    # and no style selected → block. Does NOT gate stage=extract or regen-* endpoints.
    _POST_EXTRACT = {"cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"}
    extract_done = state.stages["extract"].status.value in ("complete", "awaiting_review")
    target_includes_post_extract = (
        stage is None
        or stage in _POST_EXTRACT
    )
    if extract_done and target_includes_post_extract and not is_style_selected(project_dir, config):
        raise HTTPException(403, "Select a style before running post-extract stages.")

    if stage and rerun:
        _reset_stage_and_downstream(state, stage)
        _clear_outputs_for_rerun(project_dir, stage)
        save_state(state, project_dir)

    project_id = get_project_id(get_db(), user_id, project_name)

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue

    if stage:
        job = _run_stage_with_credits(stage, config, project_dir, state, queue, user_id, project_id)
    else:
        job = _run_full_pipeline(config, project_dir, state, queue, user_id, project_id)

    task = asyncio.create_task(_run_job(pkey, request, job))

    running[pkey] = task
    logger.info(
        "[bold blue]Pipeline queued[/] project=[white]%s[/] stage=[bold]%s[/]",
        project_name,
        stage or "all",
    )
    return {"status": "started", "stage": stage or "all"}


@router.post("/regen-extract")
async def regen_extract(
    request: Request,
    project_name: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    # Concurrency guard
    running = request.app.state.running_tasks
    existing = running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    # Keep behavior aligned with /run?stage=extract&rerun=1:
    # reset extract + all downstream stage state, and clear downstream outputs.
    _reset_stage_and_downstream(state, "extract")
    _clear_outputs_for_rerun(project_dir, "extract")
    save_state(state, project_dir)

    # Run extract stage via SSE pipeline (same pattern as POST /run?stage=extract)
    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue
    project_id = get_project_id(get_db(), user_id, project_name)
    job = _run_stage_with_credits("extract", config, project_dir, state, queue, user_id, project_id)
    task = asyncio.create_task(_run_job(pkey, request, job))
    running[pkey] = task
    logger.info(
        "[bold blue]Pipeline queued[/] project=[white]%s[/] stage=[bold]extract[/] mode=regen",
        project_name,
    )

    return {"status": "started", "stage": "extract"}


@router.get("/events")
async def event_stream(
    request: Request,
    project_name: str,
    user_id: str = Depends(get_current_user),
):
    pkey = project_key(user_id, project_name)
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
    project_name: str,
    scene_id: str = Query(...),
    panel_number: int = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    running = request.app.state.running_tasks
    existing = running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    prompt_path = project_dir / "direct" / scene_id / f"panel_{panel_number:03d}.json"
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")
    planned_panel_id = None
    try:
        from novel_to_comic.models.prompt import ImagePrompt

        planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
    except Exception:
        planned_panel_id = None

    async def _runner() -> None:
        from novel_to_comic.stages import s6_generate
        result = await s6_generate.regenerate_panel_image(
            config,
            project_dir,
            scene_id,
            panel_number,
        )
        if result.usage:
            db = get_db()
            debit_model_usage(
                db,
                user_id,
                get_project_id(db, user_id, project_name),
                result.usage,
                stage="draw",
                description=f"Model call: regenerate panel {scene_id}/{panel_number:03d}",
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


@router.post("/regen-ref")
async def regen_ref(
    request: Request,
    project_name: str,
    char_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    async def _runner() -> None:
        from novel_to_comic.stages import s2_index
        result = await s2_index.regenerate_character_ref(
            config,
            project_dir,
            char_id,
        )
        if result.usage:
            db = get_db()
            debit_model_usage(
                db,
                user_id,
                get_project_id(db, user_id, project_name),
                result.usage,
                stage="cast",
                description=f"Model call: regenerate character ref {char_id}",
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
    project_name: str,
    loc_id: str = Query(...),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    async def _runner() -> None:
        from novel_to_comic.stages import s2_index
        result = await s2_index.regenerate_location_plate(
            config,
            project_dir,
            loc_id,
        )
        if result.usage:
            db = get_db()
            debit_model_usage(
                db,
                user_id,
                get_project_id(db, user_id, project_name),
                result.usage,
                stage="cast",
                description=f"Model call: regenerate location plate {loc_id}",
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


@router.get("/generation-jobs")
def get_generation_jobs(
    request: Request,
    project_name: str,
    ids: list[str] | None = Query(None),
    user_id: str = Depends(get_current_user),
):
    pkey = project_key(user_id, project_name)
    jobs = [
        job
        for job in request.app.state.generation_jobs.values()
        if job.project_name == pkey and (ids is None or job.id in ids)
    ]
    jobs.sort(key=lambda job: job.sequence)
    return {"jobs": [generation_job_payload(request.app, job) for job in jobs]}


@router.post("/approve/{stage}")
def approve(stage: str, project_name: str, project=Depends(get_project)):
    project_dir, config, state = project
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    try:
        approve_stage(state, stage)
    except ValueError as e:
        raise HTTPException(409, str(e))
    save_state(state, project_dir)
    return {"status": "approved", "stage": stage}


@router.post("/reset/{stage}")
def reset_stage(
    stage: str,
    project_name: str,
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
    release_stage_reservations(db, user_id, get_project_id(db, user_id, project_name), stage)
    return {
        "status": "reset",
        "stage": stage,
        "message": f"Stage '{stage}' has been reset to pending. You can now re-run it."
    }


@router.post("/reset-stale")
def reset_stale(
    request: Request,
    project_name: str,
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
    project_id = get_project_id(db, user_id, project_name)
    for stage in reset:
        release_stage_reservations(db, user_id, project_id, stage)
    return {
        "status": "reset",
        "reset": reset,
        "message": f"Reset stale stages: {', '.join(reset)}",
    }


@router.get("/stage-error/{stage}")
def get_stage_error(stage: str, project_name: str, project=Depends(get_project)):
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
