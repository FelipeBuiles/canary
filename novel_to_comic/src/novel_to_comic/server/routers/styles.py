"""Style suggestion, sample generation, and active style selection."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic import artifacts
from novel_to_comic.ai import ai_request_context
from novel_to_comic.config import Config, save_config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import StageStatus, save_state
from novel_to_comic.stages.s2_style import (
    ensure_style_sample_brief,
    generate_sample_image,
    generate_samples_for_indices,
    generate_suggestions,
    load_suggestions,
    save_suggestions,
    estimate_style_batch_cost_usd,
)

from ..auth import get_current_user
from ..credits import (
    assert_sufficient_credits,
    credit_estimate_for_provider_cost,
    release_reservation,
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

router = APIRouter()


def is_style_selected(project_dir, config) -> bool:
    """Check whether an active style has been selected for this project."""
    return any(
        s.get("template", "").strip() == config.style_template.strip()
        for s in load_suggestions(project_dir)
    )


def clear_style_failures_after_selection(state) -> bool:
    """A selected style resolves partial style-sample failures for navigation.

    Failed sample attempts can leave ``items_failed`` on an otherwise completed
    style stage. Once the user chooses an active style, those failures are no
    longer blocking for downstream stages.
    """
    style_state = state.stages["style"]
    if style_state.status not in (StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW):
        return False
    if not style_state.items_failed:
        return False
    style_state.items_failed = []
    return True


def _get_bible(project_dir):
    path = artifacts.story_bible_path(project_dir)
    if not path.exists():
        return None
    return StoryBible.model_validate_json(path.read_text())


def _suggest_batch_credit_estimate(config: Config, project_dir) -> dict:
    cost_usd = estimate_style_batch_cost_usd(config, project_dir)
    return dict(credit_estimate_for_provider_cost(cost_usd, "style", reserve=True))


def _assert_no_pipeline_task(request: Request, pkey: str) -> None:
    existing = request.app.state.running_tasks.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")


def _assert_no_style_task(request: Request, pkey: str) -> None:
    existing = request.app.state.style_tasks.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A style operation is already running for this project")


@router.get("/styles")
def get_styles(project_id: str, project=Depends(get_project)):
    project_dir, config, _state = project
    suggestions = load_suggestions(project_dir)

    active_index: int | None = None
    for i, s in enumerate(suggestions, 1):
        if s.get("template", "").strip() == config.style_template.strip():
            active_index = i
            break

    result = []
    for i, s in enumerate(suggestions, 1):
        sample_path = artifacts.style_sample_path(project_dir, i)
        result.append({
            "index": i,
            "label": s.get("label", f"Style {i}"),
            "template": s.get("template", ""),
            "has_sample": sample_path.exists(),
            "is_active": i == active_index,
        })

    return {"suggestions": result, "active_index": active_index}


@router.get("/styles/suggest-estimate")
def suggest_estimate(
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the credit cost for one 'Suggest More Styles' batch (text + samples)."""
    project_dir, config, _state = project
    return _suggest_batch_credit_estimate(config, project_dir)


@router.post("/styles/suggest")
async def suggest_styles(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, _state = project
    pkey = project_key(user_id, project_id)

    _assert_no_pipeline_task(request, pkey)
    _assert_no_style_task(request, pkey)
    style_running = request.app.state.style_tasks

    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")

    estimate = _suggest_batch_credit_estimate(config, project_dir)
    required = estimate["reserved_credits"] or estimate["estimate_credits"]
    db = get_db()
    assert_sufficient_credits(db, user_id, required, action="style_suggest")
    # Share one job_id across reservation + every per-call debit so the credit
    # ledger collapses the batch into a single grouped row.
    reservation_id, job_id = reserve_credits(db, user_id, project_id, "style", required)

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue

    async def _job():
        queue.put_nowait({"type": "stage_begin", "stage": "style_suggest", "total": 1})
        try:
            queue.put_nowait({
                "type": "log", "stage": "style_suggest", "level": "info",
                "message": "Generating style suggestions...",
            })
            existing_suggestions = load_suggestions(project_dir)
            existing_count = len(existing_suggestions)
            with ai_request_context(
                user_id=user_id,
                project_id=project_id,
                project_name=project_dir.name,
                workspace_id=str(project_dir.parent),
                stage="style",
                job_id=job_id,
            ):
                new_suggestions, _usage = await generate_suggestions(
                    config, bible, existing_suggestions=existing_suggestions,
                )
                merged = existing_suggestions + new_suggestions
                save_suggestions(project_dir, merged, bible.title)
                
                total_samples = len(new_suggestions)
                queue.put_nowait({
                    "type": "stage_progress", "stage": "style_suggest",
                    "done": 0, "total": total_samples,
                })
                
                queue.put_nowait({
                    "type": "log", "stage": "style_suggest", "level": "info",
                    "message": f"Generating {total_samples} sample images...",
                })
                
                async def _on_sample_done(idx: int, result) -> None:
                    done_count = idx - existing_count
                    queue.put_nowait({
                        "type": "stage_progress", "stage": "style_suggest",
                        "done": done_count, "total": total_samples,
                    })

                new_indices = list(range(existing_count + 1, len(merged) + 1))
                await generate_samples_for_indices(
                    config, bible, project_dir, merged, new_indices,
                    on_sample_done=_on_sample_done,
                )
            queue.put_nowait({"type": "stage_progress", "stage": "style_suggest", "done": total_samples, "total": total_samples})
            queue.put_nowait({"type": "stage_complete", "stage": "style_suggest", "done": total_samples, "total": total_samples})
        except Exception as exc:
            queue.put_nowait({"type": "stage_fail", "stage": "style_suggest", "message": str(exc)})
        finally:
            if reservation_id:
                release_reservation(db, reservation_id)
            style_running.pop(pkey, None)

    task = asyncio.create_task(_job())
    style_running[pkey] = task
    return {"status": "started"}


@router.post("/styles/generate-samples")
async def generate_style_samples(
    request: Request,
    project_id: str,
    body: dict,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Regenerate sample images for specific style indices (per-card retry)."""
    project_dir, config, _state = project
    pkey = project_key(user_id, project_id)

    _assert_no_pipeline_task(request, pkey)
    _assert_no_style_task(request, pkey)

    indices = body.get("indices", [])
    if not indices or not isinstance(indices, list):
        raise HTTPException(400, "Provide non-empty 'indices' list")

    suggestions = load_suggestions(project_dir)
    if not suggestions:
        raise HTTPException(404, "No style suggestions found — run suggest first.")

    for idx in indices:
        if idx < 1 or idx > len(suggestions):
            raise HTTPException(400, f"Index {idx} out of range (1-{len(suggestions)})")

    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")

    jobs = []
    prune_finished_generation_jobs(request.app)
    for idx in indices:
        existing = find_active_generation_job(
            request.app, project_name=pkey, kind="style_sample", payload={"index": idx},
        )
        if existing:
            jobs.append(generation_job_payload(request.app, existing))
            continue

        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)

        async def _runner(sample_config=sample_config, sample_path=sample_path) -> None:
            with ai_request_context(
                user_id=user_id,
                project_id=project_id,
                project_name=project_dir.name,
                workspace_id=str(project_dir.parent),
                stage="style",
            ):
                # Disk-cached after the first sample batch, so regens reuse
                # the same scene the original samples were judged on.
                brief = await ensure_style_sample_brief(sample_config, bible, project_dir)
                await generate_sample_image(sample_config, bible, sample_path, brief=brief)

        job = enqueue_generation_job(
            request.app,
            project_name=pkey,
            kind="style_sample",
            label=f"style {idx}",
            payload={"index": idx},
            runner=_runner,
            semaphore=generation_semaphore_for_config(request.app, sample_config),
        )
        jobs.append(generation_job_payload(request.app, job))

    return {"status": "queued", "indices": indices, "jobs": jobs}


@router.patch("/styles/active")
def set_active_style(project_id: str, body: dict, project=Depends(get_project)):
    project_dir, config, state = project

    index = body.get("index")
    if index is None:
        raise HTTPException(400, "Provide 'index'")

    suggestions = load_suggestions(project_dir)
    if not suggestions:
        raise HTTPException(404, "No style suggestions found — run suggest first.")

    if index < 1 or index > len(suggestions):
        raise HTTPException(400, f"Index {index} out of range (1-{len(suggestions)})")

    template = suggestions[index - 1].get("template", config.style_template)
    config = config.model_copy(update={"style_template": template})
    save_config(config, project_dir)
    if clear_style_failures_after_selection(state):
        save_state(state, project_dir)

    return {"status": "updated", "index": index, "style_template": template}
