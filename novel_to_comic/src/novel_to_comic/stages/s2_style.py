"""Stage 2: Generate visual style suggestions for review.

Calls the LLM once to produce five diverse style templates from the story
bible, saves them to samples/style_suggestions.json, then enters
awaiting_review so the user can preview samples and pick an active style
before the cast stage runs.
"""

import json
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.clients import text as text_client
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_api_usage,
    record_item_done,
    save_state,
)

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
    story_bible,
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


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 2: Generate visual style suggestions for review."""
    emit = on_event or _NOOP

    suggestions_path = artifacts.style_suggestions_path(project_dir)

    begin_stage(state, "style", total=1)
    emit({"type": "stage_begin", "stage": "style", "total": 1})
    save_state(state, project_dir)

    try:
        if not suggestions_path.exists():
            story_bible = artifacts.read_story_bible(project_dir)
            suggestions, usage = await generate_suggestions(config, story_bible)
            if usage:
                record_api_usage(state, "style", usage)
            suggestions_path.parent.mkdir(parents=True, exist_ok=True)
            suggestions_path.write_text(
                json.dumps({"title": story_bible.title, "suggestions": suggestions}, indent=2)
            )
            emit({
                "type": "log", "stage": "style", "level": "info",
                "message": f"Generated {len(suggestions)} style suggestions.",
            })
        else:
            emit({
                "type": "log", "stage": "style", "level": "dim",
                "message": "Style suggestions already exist — awaiting selection.",
            })

        record_item_done(state, "style")
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
