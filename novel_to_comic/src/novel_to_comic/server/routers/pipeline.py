"""Pipeline execution, SSE streaming, and checkpoint approval."""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from novel_to_comic.state import (
    STAGE_NAMES,
    StageStatus,
    approve_stage,
    save_state,
)

from ..deps import get_project

router = APIRouter()


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
    runner = _stage_runner(stage, config, project_dir, state)
    if not runner:
        queue.put_nowait({"type": "stage_fail", "stage": stage, "message": f"Unknown stage: {stage}"})
        return
    try:
        await runner(on_event=lambda e: queue.put_nowait(e))
    except Exception as exc:
        queue.put_nowait({"type": "stage_fail", "stage": stage, "message": str(exc)})


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
    return {"status": "started", "stage": stage or "all"}


@router.get("/events")
async def event_stream(request: Request, project_name: str):
    queue = request.app.state.event_queues.get(project_name)
    if not queue:
        raise HTTPException(404, "No active run for this project")

    async def generator():
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
                    break
        finally:
            task = request.app.state.running_tasks.get(project_name)
            if task is None or task.done():
                request.app.state.event_queues.pop(project_name, None)

    return StreamingResponse(generator(), media_type="text/event-stream")


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
