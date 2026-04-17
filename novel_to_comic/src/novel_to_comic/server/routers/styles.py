"""Style suggestion, sample generation, and active style selection."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic.config import Config, load_config, save_config
from novel_to_comic.models.story_bible import StoryBible

from ..deps import get_project
from ..generation_jobs import (
    enqueue_generation_job,
    generation_job_payload,
    prune_finished_generation_jobs,
)

router = APIRouter()


def _load_suggestions(project_dir):
    path = project_dir / "samples" / "style_suggestions.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("suggestions") if isinstance(data, dict) else data
    except Exception:
        return None


def _save_suggestions(project_dir, suggestions, title):
    path = project_dir / "samples" / "style_suggestions.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"title": title, "suggestions": suggestions}, indent=2))


async def _suggest_styles(config: Config, bible) -> list[dict]:
    from novel_to_comic.clients import gemini

    system = (
        "You are a visual art director for adapted fiction. Given a story's details, generate 5 "
        "distinct visual style templates for image generation prompts. "
        "Span the full medium spectrum — do NOT default to illustrated or comic styles. "
        "At least one suggestion must be photorealistic or cinematic. "
        "Include a range: e.g. cinematic live-action, painterly, stylised illustration, graphic novel, "
        "anime/manga — pick whichever 5 best suit this specific story. "
        "Each is a single paragraph of 40-70 words describing: medium/rendering style, color palette, "
        "lighting, composition, mood. Make each genuinely distinct. Output a JSON array only, no markdown."
    )
    user = (
        f'Story: "{bible.title}" by {bible.author}\n'
        f"Style notes: {bible.style_notes or 'none'}\n"
        f"Genre/tone: {', '.join({s.scene_type for s in bible.scenes})}\n"
        f"Characters: {'; '.join(f'{c.name} ({c.gender}, {c.age_range})' for c in bible.characters[:5])}\n\n"
        f"Generate 5 style options that genuinely serve this story. "
        f"Consider what rendering style would best capture the tone — not just what looks 'comic-like'. "
        f"Output JSON array of 5 objects: "
        f'[{{"label": "Style Name (2-4 words)", "template": "40-70 word description"}}, ...]'
    )

    result = await gemini.generate_json(
        config=config, model=config.screenplay_model,
        system_prompt=system, user_content=user,
    )
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("styles", [])
    return []


async def _generate_style_sample(config, bible, project_dir, sample_path):
    from novel_to_comic.clients import flux

    first_char = bible.characters[0] if bible.characters else None
    first_loc = bible.locations[0] if bible.locations else None

    char_desc = (first_char.visual_anchor or first_char.name)[:200] if first_char else "a mysterious cloaked figure"
    loc_desc = (first_loc.visual_anchor or first_loc.name)[:200] if first_loc else "a dramatic atmospheric setting"

    prompt = (
        f"{config.style_template}\n\n"
        f"{char_desc}. Set in: {loc_desc}. "
        f"Medium shot, eye-level camera, dramatic lighting. "
        f"No text. No speech bubbles. No captions. Single panel only."
    )

    sample_path.parent.mkdir(exist_ok=True)
    await flux.generate_image(config=config, prompt=prompt, output_path=sample_path)


async def _generate_style_samples_parallel(config, bible, project_dir, indices, suggestions):
    samples_dir = project_dir / "samples"
    samples_dir.mkdir(exist_ok=True)

    async def _one(idx: int) -> None:
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = samples_dir / f"style_{idx}.png"
        await _generate_style_sample(sample_config, bible, project_dir, sample_path)

    await asyncio.gather(*[_one(i) for i in indices])


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
async def suggest_styles(request: Request, project_name: str, project=Depends(get_project)):
    project_dir, config, state = project

    running = request.app.state.running_tasks
    existing = running.get(project_name)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")

    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")

    queue: asyncio.Queue = asyncio.Queue()
    request.app.state.event_queues[project_name] = queue

    async def _job():
        queue.put_nowait({"type": "stage_begin", "stage": "style_suggest", "total": 1})
        try:
            queue.put_nowait({
                "type": "log",
                "stage": "style_suggest",
                "level": "info",
                "message": "Generating style suggestions...",
            })
            suggestions = await _suggest_styles(config, bible)
            _save_suggestions(project_dir, suggestions, bible.title)
            queue.put_nowait({"type": "stage_progress", "stage": "style_suggest", "done": 1, "total": 1})
            queue.put_nowait({"type": "stage_complete", "stage": "style_suggest", "done": 1, "total": 1})
        except Exception as exc:
            queue.put_nowait({"type": "stage_fail", "stage": "style_suggest", "message": str(exc)})

    from .pipeline import _run_job
    task = asyncio.create_task(_run_job(project_name, request, _job()))
    running[project_name] = task
    return {"status": "started"}


@router.post("/styles/generate-samples")
async def generate_style_samples(
    request: Request,
    project_name: str,
    body: dict,
    project=Depends(get_project),
):
    project_dir, config, state = project

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
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = project_dir / "samples" / f"style_{idx}.png"

        async def _runner(
            sample_config=sample_config,
            sample_path=sample_path,
        ) -> None:
            async with request.app.state.generation_semaphore:
                await _generate_style_sample(sample_config, bible, project_dir, sample_path)

        job = enqueue_generation_job(
            request.app,
            project_name=project_name,
            kind="style_sample",
            label=f"style {idx}",
            payload={"index": idx},
            runner=_runner,
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
