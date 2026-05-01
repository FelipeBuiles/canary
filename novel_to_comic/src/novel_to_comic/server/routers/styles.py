"""Style suggestion, sample generation, and active style selection."""

import asyncio
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic.config import Config, save_config
from novel_to_comic.ai import ai_request_context
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import build_style_sample_prompt
from novel_to_comic.stages.s2_style import generate_suggestions

from ..auth import get_current_user
from ..credits import debit_model_usage, get_project_id
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


def _sample_meta_path(sample_path):
    return sample_path.with_suffix(f"{sample_path.suffix}.meta.json")


def _style_sample_meta(config: Config, prompt: str) -> dict:
    return {
        "version": 1,
        "kind": "style_sample",
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "parameters": {
            "image_model": config.effective_image_model(),
            "width": config.image_width,
            "height": config.image_height,
            "steps": config.effective_image_steps(),
            "guidance_scale": config.flux_guidance_scale,
            "style_template": config.style_template,
        },
    }


def _load_suggestions(project_dir):
    path = project_dir / "samples" / "style_suggestions.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("suggestions") if isinstance(data, dict) else data
    except Exception:
        return None


def is_style_selected(project_dir, config) -> bool:
    """Check whether an active style has been selected for this project."""
    suggestions = _load_suggestions(project_dir) or []
    return any(
        s.get("template", "").strip() == config.style_template.strip()
        for s in suggestions
    )


def _save_suggestions(project_dir, suggestions, title):
    path = project_dir / "samples" / "style_suggestions.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"title": title, "suggestions": suggestions}, indent=2))




async def _generate_style_sample(config, bible, project_dir, sample_path, user_id: str, project_id: str | None):
    from novel_to_comic.clients import flux
    from novel_to_comic.usage import calculate_cost
    prompt = build_style_sample_prompt(config, bible)
    meta = _style_sample_meta(config, prompt)

    sample_path.parent.mkdir(exist_ok=True)
    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="style",
    ):
        result = await flux.generate_image(
            config=config,
            prompt=prompt,
            output_path=sample_path,
            feature="style.sample",
        )
    if result.usage:
        meta["cost_usd"] = round(calculate_cost(result.usage), 6)
        meta["usage"] = result.usage.model_dump()
    _sample_meta_path(sample_path).write_text(json.dumps(meta, indent=2, sort_keys=True))
    return result


async def _generate_style_samples_parallel(config, bible, project_dir, indices, suggestions, user_id: str, project_id: str | None):
    from novel_to_comic.state import load_state, record_misc_usage, save_state
    samples_dir = project_dir / "samples"
    samples_dir.mkdir(exist_ok=True)

    async def _one(idx: int) -> None:
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = samples_dir / f"style_{idx}.png"
        result = await _generate_style_sample(sample_config, bible, project_dir, sample_path, user_id, project_id)
        if result.usage:
            state = load_state(project_dir)
            record_misc_usage(state, result.usage)
            save_state(state, project_dir)
            debit_model_usage(
                get_db(),
                user_id,
                project_id,
                result.usage,
                description=f"Model call: style sample {idx}",
            )

    sem = asyncio.Semaphore(2)

    async def _limited(idx: int) -> None:
        async with sem:
            await _one(idx)

    await asyncio.gather(*[_limited(i) for i in indices])


def _get_bible(project_dir):
    path = project_dir / "story_bible.json"
    if not path.exists():
        return None
    return StoryBible.model_validate_json(path.read_text())


@router.get("/styles")
def get_styles(project_name: str, project=Depends(get_project)):
    project_dir, config, state = project
    suggestions = _load_suggestions(project_dir) or []

    active_index: int | None = None
    for i, s in enumerate(suggestions, 1):
        if s.get("template", "").strip() == config.style_template.strip():
            active_index = i
            break

    result = []
    for i, s in enumerate(suggestions, 1):
        sample_path = project_dir / "samples" / f"style_{i}.png"
        result.append({
            "index": i,
            "label": s.get("label", f"Style {i}"),
            "template": s.get("template", ""),
            "has_sample": sample_path.exists(),
            "is_active": i == active_index,
        })

    return {"suggestions": result, "active_index": active_index}


@router.post("/styles/suggest")
async def suggest_styles(
    request: Request,
    project_name: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    style_running = request.app.state.style_tasks
    existing = style_running.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A style operation is already running for this project")

    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[pkey] = queue

    async def _job():
        queue.put_nowait({"type": "stage_begin", "stage": "style_suggest", "total": 1})
        try:
            queue.put_nowait({
                "type": "log",
                "stage": "style_suggest",
                "level": "info",
                "message": "Generating style suggestions...",
            })
            existing = _load_suggestions(project_dir) or []
            existing_labels = [s.get("label", "") for s in existing if isinstance(s, dict)]
            project_id = get_project_id(get_db(), user_id, project_name)
            with ai_request_context(
                user_id=user_id,
                project_id=project_id,
                project_name=project_dir.name,
                workspace_id=str(project_dir.parent),
                stage="style",
            ):
                new_suggestions, usage = await generate_suggestions(
                    config,
                    bible,
                    existing_labels=existing_labels,
                )
            if usage:
                debit_model_usage(
                    get_db(),
                    user_id,
                    project_id,
                    usage,
                    description="Model call: style suggestions",
                )
            _save_suggestions(project_dir, existing + new_suggestions, bible.title)
            queue.put_nowait({"type": "stage_progress", "stage": "style_suggest", "done": 1, "total": 1})
            queue.put_nowait({"type": "stage_complete", "stage": "style_suggest", "done": 1, "total": 1})
        except Exception as exc:
            queue.put_nowait({"type": "stage_fail", "stage": "style_suggest", "message": str(exc)})
        finally:
            style_running.pop(pkey, None)

    task = asyncio.create_task(_job())
    style_running[pkey] = task
    return {"status": "started"}


@router.post("/styles/generate-samples")
async def generate_style_samples(
    request: Request,
    project_name: str,
    body: dict,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)

    indices = body.get("indices", [])
    if not indices or not isinstance(indices, list):
        raise HTTPException(400, "Provide non-empty 'indices' list")

    suggestions = _load_suggestions(project_dir)
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
            request.app,
            project_name=pkey,
            kind="style_sample",
            payload={"index": idx},
        )
        if existing:
            jobs.append(generation_job_payload(request.app, existing))
            continue

        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = project_dir / "samples" / f"style_{idx}.png"

        project_id = get_project_id(get_db(), user_id, project_name)

        async def _runner(
            sample_config=sample_config,
            sample_path=sample_path,
            project_id=project_id,
            _sample_idx=idx,
        ) -> None:
            result = await _generate_style_sample(
                sample_config,
                bible,
                project_dir,
                sample_path,
                user_id,
                project_id,
            )
            if result.usage:
                from novel_to_comic.state import load_state, record_misc_usage, save_state
                st = load_state(project_dir)
                record_misc_usage(st, result.usage)
                save_state(st, project_dir)
                debit_model_usage(
                    get_db(),
                    user_id,
                    project_id,
                    result.usage,
                    description=f"Model call: style sample {_sample_idx}",
                )

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
def set_active_style(project_name: str, body: dict, project=Depends(get_project)):
    project_dir, config, state = project

    index = body.get("index")
    if index is None:
        raise HTTPException(400, "Provide 'index'")

    suggestions = _load_suggestions(project_dir)
    if not suggestions:
        raise HTTPException(404, "No style suggestions found — run suggest first.")

    if index < 1 or index > len(suggestions):
        raise HTTPException(400, f"Index {index} out of range (1-{len(suggestions)})")

    template = suggestions[index - 1].get("template", config.style_template)
    config = config.model_copy(update={"style_template": template})
    save_config(config, project_dir)

    return {"status": "updated", "index": index, "style_template": template}
