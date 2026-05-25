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
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import build_style_sample_prompt
from novel_to_comic.stage_runtime import StageRuntime

SAMPLE_COUNT = 5
SAMPLE_CONCURRENCY = 2

_SYSTEM_PROMPT = (
    "You are a visual art director for adapted fiction. Surface 5 genuinely distinctive "
    "visual styles a comic adaptation of this story could take.\n\n"

    "Work in two passes:\n"
    "1) BRAINSTORM (silently, before writing output). List 20-30 candidate visual "
    "traditions, movements, mediums, eras, named artists, illustrators, magazines, "
    "studios, films, or subcultural visual languages that could plausibly carry this "
    "story. Range widely — vernacular alongside fine art, obscure alongside familiar, "
    "different centuries, different regions, different intents (decorative, documentary, "
    "satirical, devotional, commercial, journalistic, instructional, scientific).\n"
    "2) CURATE. From that pool, choose the 5 that are MOST DISTINCT FROM ONE ANOTHER — "
    "not the 5 best fits. Spread them across mediums, eras, and visual logics so no two "
    "could be mistaken for each other at a glance.\n\n"

    "Every template must explicitly name at least one real anchor: a specific artist, "
    "illustrator, magazine, studio, film, decade, movement, region, or publication. "
    "Concreteness drives variance — avoid abstract descriptors that could apply to "
    "anything (\"moody painterly\", \"flat geometric\"). At least 3 of the 5 should "
    "match the story's mood; at least 1 should productively contradict it.\n\n"

    "Each template is a single paragraph of 40-70 words of vivid, specific visual "
    "direction. Describe a general visual aesthetic only — do not reference characters, "
    "locations, or plot from the story; those get combined in later. Vary sentence "
    "structure and what you emphasize across the 5.\n\n"

    "Output JSON array only, no markdown: "
    '[{"label": "Style Name (2-4 words)", "template": "40-70 word description"}, ...]'
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
        f"Generate 5 style options for this story."
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


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> None:
    """Execute Stage 2: 5 style suggestions + 5 sample images."""
    bible = artifacts.read_story_bible(project_dir)
    existing_suggestions = load_suggestions(project_dir)
    needs_suggestions = not existing_suggestions
    pending_sample_indices = (
        list(range(1, SAMPLE_COUNT + 1))
        if needs_suggestions
        else missing_sample_indices(project_dir, existing_suggestions)
    )
    total = (1 if needs_suggestions else 0) + len(pending_sample_indices)

    with ctx.execute(total=total):
        if needs_suggestions:
            suggestions, usage = await generate_suggestions(config, bible)
            if usage:
                ctx.record_api_usage(usage)
            save_suggestions(project_dir, suggestions, bible.title)
            ctx.record_item_done()
            ctx.log(f"Generated {len(suggestions)} style suggestions.")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            ctx.save()
            pending_sample_indices = list(range(1, len(suggestions) + 1))
        else:
            suggestions = existing_suggestions
            ctx.log("Style suggestions already exist — generating missing samples.", level="dim")

        async def _record(_idx: int, result) -> None:
            if result.usage:
                ctx.record_item_done(usage=result.usage)
            else:
                ctx.record_item_done()
            ctx.save()
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)

        if pending_sample_indices:
            await generate_samples_for_indices(
                config,
                bible,
                project_dir,
                suggestions,
                pending_sample_indices,
                on_sample_done=_record,
            )


from novel_to_comic.stages import Stage  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_text_cost, estimate_image_cost

    suggestions = load_suggestions(project_dir)
    needs_suggestions = not suggestions
    if needs_suggestions:
        story_bible_text = ""
        sb_path = artifacts.story_bible_path(project_dir)
        if sb_path.exists():
            try:
                story_bible_text = sb_path.read_text()[:3000]
            except Exception:
                pass
        text_cost = estimate_text_cost(
            config.effective_prompt_model(),
            story_bible_text,
        )
        sample_count = SAMPLE_COUNT
    else:
        text_cost = 0.0
        sample_count = len(missing_sample_indices(project_dir, suggestions))

    image_cost = estimate_image_cost(
        config.effective_image_model(),
        sample_count,
        quality=getattr(config, "image_quality", None),
    )
    return text_cost + image_cost


def estimate_style_batch_cost_usd(config: Config, project_dir: Path) -> float:
    """Estimate provider cost for one 'Suggest More Styles' batch (text + samples)."""
    from novel_to_comic.usage import estimate_text_cost, estimate_image_cost

    story_bible_text = ""
    sb_path = artifacts.story_bible_path(project_dir)
    if sb_path.exists():
        try:
            story_bible_text = sb_path.read_text()[:3000]
        except Exception:
            pass

    text_cost = estimate_text_cost(
        config.effective_prompt_model(),
        story_bible_text,
    )
    image_cost = estimate_image_cost(
        config.effective_image_model(),
        SAMPLE_COUNT,
        quality=getattr(config, "image_quality", None),
    )
    return text_cost + image_cost


STAGE = Stage(
    name="style",
    run=run,
    outputs=lambda d: [artifacts.style_suggestions_path(d)],
    clean_paths=lambda d: [
        d / "samples", d / "refs", d / "plates",
        d / "adapt", d / "plan", d / "storyboard",
        d / "direct", d / "draw", d / "compose", d / "exports",
    ],
    estimate_cost=estimate_cost,
)
