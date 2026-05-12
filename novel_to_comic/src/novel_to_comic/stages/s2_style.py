"""Stage 2: Generate visual style options for review.

Produces five distinct style templates (text descriptions) and one sample
image per style, then enters awaiting_review so the user can preview the
samples and pick an active style before downstream stages run.
"""

import asyncio
import hashlib
import json
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.clients import flux, text as text_client
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import build_style_sample_prompt
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_api_usage,
    record_item_done,
    save_state,
)

SAMPLE_COUNT = 5
SAMPLE_CONCURRENCY = 2

_SYSTEM_PROMPT = (
    "You are a visual art director for adapted fiction. Given a story's details, generate 5 "
    "distinct visual style templates for image generation prompts. "
    "Each style must come from a completely different visual tradition — span painting, printmaking, "
    "photography, animation, textile, folk art, editorial, fine art, street art, or any other visual language. "
    "Do NOT default to cinematic or photorealistic. "
    "At least 3 of the 5 should complement the story's mood — but include at least 1 unexpected or contrasting choice "
    "that could reveal a surprising side of the story. "
    "Each template is a single paragraph of 40-70 words of vivid, specific visual direction. "
    "Prioritize controlled, readable rendering with coherent shapes and intentional marks. "
    "Do not ask for stochastic grain, noisy speckling, all-over dappling, repeated texture fields, "
    "compression artifacts, muddy micro-detail, or pattern tiling. If a style includes brushwork, "
    "hatching, weave, or other surface treatment, describe it as broad intentional structure rather "
    "than noise. "
    "Write naturally — do NOT follow a rigid 'medium, palette, lighting, composition, mood' formula. "
    "Vary sentence structure, what you emphasize, and how you describe each style. "
    "Output a JSON array only, no markdown. "
)


async def generate_suggestions(
    config: Config,
    story_bible: StoryBible,
    *,
    existing_labels: list[str] | None = None,
):
    """Generate style suggestions via LLM. Returns (suggestions_list, usage)."""
    avoid = ""
    if existing_labels:
        joined = ", ".join(f'"{label}"' for label in existing_labels)
        avoid = (
            f"\nThese styles have already been suggested and must NOT be repeated or closely paraphrased: "
            f"[{joined}]. "
        )

    system = (
        _SYSTEM_PROMPT
        + avoid
        + config.generation_language_instruction()
    )
    user = (
        f'Story: "{story_bible.title}" by {story_bible.author}\n'
        f"Style notes: {story_bible.style_notes or 'none'}\n"
        f"Genre/tone: {', '.join({s.scene_type for s in story_bible.scenes})}\n\n"
        f"Generate 5 style options that would suit this story's tone. "
        f"Each template must describe a general visual aesthetic — do NOT reference specific characters, "
        f"locations, or plot elements from the story. The template will be combined with story details later, "
        f"so it should only define the visual style (medium, palette, surface handling, atmosphere). "
        f"Output JSON array of 5 objects: "
        f'[{{"label": "Style Name (2-4 words)", "template": "40-70 word description"}}, ...]'
    )

    api_result = await text_client.generate_json(
        config=config,
        model=config.effective_prompt_model(),
        system_prompt=system,
        user_content=user,
        temperature=1.0,
        feature="style.suggestions",
    )
    result = api_result.value
    if isinstance(result, list):
        return result, api_result.usage
    if isinstance(result, dict):
        return result.get("styles", []), api_result.usage
    return [], api_result.usage


def _sample_meta_path(sample_path: Path) -> Path:
    return sample_path.with_suffix(f"{sample_path.suffix}.meta.json")


def _sample_meta(config: Config, prompt: str) -> dict:
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


async def generate_sample_image(
    config: Config,
    bible: StoryBible,
    sample_path: Path,
):
    """Generate one style sample image at sample_path. Returns ApiResult."""
    prompt = build_style_sample_prompt(config, bible)
    meta = _sample_meta(config, prompt)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    result = await flux.generate_image(
        config=config,
        prompt=prompt,
        output_path=sample_path,
        feature="style.sample",
    )
    _sample_meta_path(sample_path).write_text(json.dumps(meta, indent=2, sort_keys=True))
    return result


def load_suggestions(project_dir: Path) -> list[dict]:
    """Read the suggestions list from disk, or return [] if missing."""
    path = artifacts.style_suggestions_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if isinstance(data, dict):
        return data.get("suggestions", []) or []
    if isinstance(data, list):
        return data
    return []


def save_suggestions(project_dir: Path, suggestions: list[dict], title: str) -> None:
    path = artifacts.style_suggestions_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"title": title, "suggestions": suggestions}, indent=2))


def missing_sample_indices(project_dir: Path, suggestions: list[dict]) -> list[int]:
    """Return 1-indexed positions of suggestions that don't have a sample image."""
    return [
        idx
        for idx in range(1, len(suggestions) + 1)
        if not artifacts.style_sample_path(project_dir, idx).exists()
    ]


async def generate_samples_for_indices(
    config: Config,
    bible: StoryBible,
    project_dir: Path,
    suggestions: list[dict],
    indices: list[int],
    *,
    on_sample_done=None,
    concurrency: int = SAMPLE_CONCURRENCY,
) -> None:
    """Generate sample images for the given 1-indexed suggestions in parallel.

    `on_sample_done(idx, ApiResult)` is awaited after each sample finishes —
    callers use it to record per-item progress and persist incremental state.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(idx: int) -> None:
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)
        async with sem:
            result = await generate_sample_image(sample_config, bible, sample_path)
        if on_sample_done is not None:
            await on_sample_done(idx, result)

    await asyncio.gather(*[_one(i) for i in indices])


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 2: 5 style suggestions + 5 sample images."""
    emit = on_event or _NOOP

    bible = artifacts.read_story_bible(project_dir)
    existing_suggestions = load_suggestions(project_dir)
    needs_suggestions = not existing_suggestions
    pending_sample_indices = (
        list(range(1, SAMPLE_COUNT + 1))
        if needs_suggestions
        else missing_sample_indices(project_dir, existing_suggestions)
    )
    total = (1 if needs_suggestions else 0) + len(pending_sample_indices)

    begin_stage(state, "style", total=total)
    emit({"type": "stage_begin", "stage": "style", "total": total})
    save_state(state, project_dir)

    try:
        if needs_suggestions:
            suggestions, usage = await generate_suggestions(config, bible)
            if usage:
                record_api_usage(state, "style", usage)
            save_suggestions(project_dir, suggestions, bible.title)
            record_item_done(state, "style")
            emit({
                "type": "log", "stage": "style", "level": "info",
                "message": f"Generated {len(suggestions)} style suggestions.",
            })
            emit({
                "type": "stage_progress", "stage": "style",
                "done": state.stages["style"].items_done,
                "total": state.stages["style"].items_total,
            })
            save_state(state, project_dir)
            pending_sample_indices = list(range(1, len(suggestions) + 1))
        else:
            suggestions = existing_suggestions
            emit({
                "type": "log", "stage": "style", "level": "dim",
                "message": "Style suggestions already exist — generating missing samples.",
            })

        async def _record(_idx: int, result) -> None:
            if result.usage:
                record_item_done(state, "style", usage=result.usage)
            else:
                record_item_done(state, "style")
            save_state(state, project_dir)
            emit({
                "type": "stage_progress", "stage": "style",
                "done": state.stages["style"].items_done,
                "total": state.stages["style"].items_total,
            })

        if pending_sample_indices:
            await generate_samples_for_indices(
                config,
                bible,
                project_dir,
                suggestions,
                pending_sample_indices,
                on_sample_done=_record,
            )

        complete_stage(state, "style")
        emit({
            "type": "stage_complete", "stage": "style",
            "done": state.stages["style"].items_done,
            "total": state.stages["style"].items_total,
        })
        save_state(state, project_dir)

    except Exception as e:
        fail_stage(state, "style", str(e))
        emit({"type": "stage_fail", "stage": "style", "message": str(e)})
        save_state(state, project_dir)
        raise


from novel_to_comic.stages import Stage  # noqa: E402

STAGE = Stage(
    name="style",
    run=run,
    outputs=lambda d: [artifacts.style_suggestions_path(d)],
    clean_paths=lambda d: [
        d / "samples", d / "refs", d / "plates",
        d / "adapt", d / "plan", d / "storyboard",
        d / "direct", d / "draw", d / "compose", d / "exports",
    ],
)
