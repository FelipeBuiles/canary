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
    save_state,
)

from ..deps import get_project
from ..generation_jobs import (
    enqueue_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)

router = APIRouter()
logger = logging.getLogger("canary.pipeline")


def _stage_runner(stage: str, config, project_dir, state):
    """Import and return the async run() coroutine for a given stage."""
    from novel_to_comic.stages import (
        s1_extract, s2_index, s3_screenplay,
        s4_panels, s5_prompts, s6_generate, s7_assemble,
    )
    runners = {
        "extract":    lambda on_event: s1_extract.run(config, project_dir, state, on_event=on_event),
        "index":      lambda on_event: s2_index.run(config, project_dir, state, on_event=on_event),
        "screenplay": lambda on_event: s3_screenplay.run(config, project_dir, state, on_event=on_event),
        "panels":     lambda on_event: s4_panels.run(config, project_dir, state, on_event=on_event),
        "prompts":    lambda on_event: s5_prompts.run(config, project_dir, state, on_event=on_event),
        "generate":   lambda on_event: s6_generate.run(config, project_dir, state, on_event=on_event),
        "assemble":   lambda on_event: s7_assemble.run(config, project_dir, state, on_event=on_event),
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


async def _run_full_pipeline(config, project_dir, state, queue: asyncio.Queue):
    """Run all stages in order, stopping at checkpoints or failures."""
    for stage in STAGE_NAMES:
        s = state.stages[stage]
        if s.status.value in ("complete",):
            continue
        if s.status == StageStatus.AWAITING_REVIEW:
            queue.put_nowait({
                "type": "log", "stage": stage, "level": "warn",
                "message": f"Stage '{stage}' is awaiting review — stopping.",
            })
            break

        await _run_stage(stage, config, project_dir, state, queue)

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


async def _run_job(project_name: str, request: Request, job):
    """Wrap a pipeline task so lifecycle cleanup is consistent."""
    try:
        await job
    finally:
        queue = request.app.state.event_queues.get(project_name)
        if queue is not None:
            queue.put_nowait({"type": "pipeline_done"})
        request.app.state.running_tasks.pop(project_name, None)
        # Schedule cleanup of the event queue if no SSE client drains it.
        # This prevents orphaned queues when a client disconnects before
        # receiving pipeline_done.
        asyncio.get_event_loop().call_later(
            60,
            _cleanup_stale_queue,
            request.app,
            project_name,
            queue,
        )


def _cleanup_stale_queue(app, project_name: str, queue) -> None:
    """Remove an event queue if it's still the same one and no task owns it."""
    current = app.state.event_queues.get(project_name)
    if current is not queue:
        return  # a new run replaced it
    task = app.state.running_tasks.get(project_name)
    if task is not None and not task.done():
        return  # a new run is active
    app.state.event_queues.pop(project_name, None)


@router.post("/run")
async def run_pipeline(
    request: Request,
    project_name: str,
    stage: Optional[str] = Query(None),
    project=Depends(get_project),
):
    project_dir, config, state = project

    if stage and stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage: {stage}. Valid: {STAGE_NAMES}")

    # Concurrency guard
    running = request.app.state.running_tasks
    existing = running.get(project_name)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[project_name] = queue

    if stage:
        job = _run_stage(stage, config, project_dir, state, queue)
    else:
        job = _run_full_pipeline(config, project_dir, state, queue)

    task = asyncio.create_task(_run_job(project_name, request, job))

    running[project_name] = task
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
):
    project_dir, config, state = project

    # Concurrency guard
    running = request.app.state.running_tasks
    existing = running.get(project_name)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    # Reset all downstream stages to pending
    extract_idx = STAGE_NAMES.index("extract")
    for stage_name in STAGE_NAMES[extract_idx + 1:]:
        state.stages[stage_name] = StageState()

    # Also reset extract itself so it re-runs cleanly
    state.stages["extract"] = StageState()
    save_state(state, project_dir)

    # Delete stale extract artifacts
    story_bible = project_dir / "story_bible.json"
    if story_bible.exists():
        story_bible.unlink()
    scenes_dir = project_dir / "scenes"
    if scenes_dir.exists():
        shutil.rmtree(scenes_dir)

    # Run extract stage via SSE pipeline (same pattern as POST /run?stage=extract)
    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[project_name] = queue
    job = _run_stage("extract", config, project_dir, state, queue)
    task = asyncio.create_task(_run_job(project_name, request, job))
    running[project_name] = task
    logger.info(
        "[bold blue]Pipeline queued[/] project=[white]%s[/] stage=[bold]extract[/] mode=regen",
        project_name,
    )

    return {"status": "started", "stage": "extract"}


@router.get("/events")
async def event_stream(request: Request, project_name: str):
    queue = request.app.state.event_queues.get(project_name)
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
            task = request.app.state.running_tasks.get(project_name)
            current_queue = request.app.state.event_queues.get(project_name)
            if current_queue is queue and (completed or task is None or task.done()):
                request.app.state.event_queues.pop(project_name, None)

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/regen")
async def regen_panel(
    request: Request,
    project_name: str,
    scene_id: str = Query(...),
    panel_number: int = Query(...),
    project=Depends(get_project),
):
    project_dir, config, state = project

    running = request.app.state.running_tasks
    existing = running.get(project_name)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    prompt_path = project_dir / "prompts" / scene_id / f"panel_{panel_number:03d}.json"
    if not prompt_path.exists():
        raise HTTPException(404, f"Prompt not found: {scene_id}/panel_{panel_number:03d}")

    async def _runner() -> None:
        from novel_to_comic.stages import s6_generate
        await s6_generate.regenerate_panel_image(
            config,
            project_dir,
            scene_id,
            panel_number,
        )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=project_name,
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
    }


@router.post("/regen-ref")
async def regen_ref(
    request: Request,
    project_name: str,
    char_id: str = Query(...),
    project=Depends(get_project),
):
    project_dir, config, state = project

    async def _runner() -> None:
        from novel_to_comic.stages import s2_index
        await s2_index.regenerate_character_ref(
            config,
            project_dir,
            char_id,
        )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=project_name,
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
):
    project_dir, config, state = project

    async def _runner() -> None:
        from novel_to_comic.stages import s2_index
        await s2_index.regenerate_location_plate(
            config,
            project_dir,
            loc_id,
        )

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=project_name,
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
):
    jobs = [
        job
        for job in request.app.state.generation_jobs.values()
        if job.project_name == project_name and (ids is None or job.id in ids)
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
