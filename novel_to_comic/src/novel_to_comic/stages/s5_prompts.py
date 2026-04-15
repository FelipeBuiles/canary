"""Stage 5: Panel JSON → Image prompts via Gemini Flash.

Assembles the final image prompt from 4 components:
  [STYLE TEMPLATE] + [LOCATION ANCHOR] + [CHARACTER ANCHOR(S)] + [SCENE DIRECTION]
  + "No text. No speech bubbles. No captions. No lettering. Single panel only."
"""

import asyncio
import json
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from novel_to_comic.clients import gemini
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    record_item_failed,
    save_state,
)

console = Console()
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "image_prompt.txt"

# Portrait dimensions per shot type.
# Panels in the default 6-panel layout (3 cols × 2 rows) are roughly 1:2 portrait.
# Generating at portrait ratios avoids the severe horizontal cropping that happens
# when a square image is displayed in a tall narrow panel with object-fit: cover.
_SHOT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "close-up":      (768, 1024),   # 3:4  — face fills frame, less vertical needed
    "over-shoulder": (768, 1024),   # 3:4  — two-shot, upper body
    "medium":        (768, 1344),   # 4:7  — full body portrait
    "wide":          (768, 1344),   # 4:7  — full scene, characters small
    "extreme-wide":  (768, 1344),   # 4:7  — establishing, environment dominates
}
_DEFAULT_DIMENSIONS = (768, 1344)


def _dimensions_for_shot(shot_type: str) -> tuple[int, int]:
    """Return (width, height) for a given shot type."""
    return _SHOT_DIMENSIONS.get(shot_type.lower().replace(" ", "-"), _DEFAULT_DIMENSIONS)


def _load_story_bible(project_dir: Path) -> StoryBible:
    return StoryBible.model_validate_json((project_dir / "story_bible.json").read_text())


def _build_user_content(
    panel: PanelBreakdown, story_bible: StoryBible, config: Config, project_dir: Path,
) -> str:
    """Build the input for the prompt assembly LLM."""
    char_count = len(panel.characters_present)

    # Character anchors — expression and action are surfaced first so the image
    # model weights them highly; the visual anchor text follows verbatim.
    char_sections = []
    ref_paths = []
    for cid in panel.characters_present:
        char = next((c for c in story_bible.characters if c.id == cid), None)
        if char:
            expr = panel.character_expressions.get(cid, "")
            action = panel.character_actions.get(cid, "")
            moment = ", ".join(filter(None, [action, expr]))
            moment_line = f"In this panel: {moment}" if moment else ""
            char_sections.append(
                f"CHARACTER ({char.name}, {cid}):\n{moment_line}\n{char.visual_anchor}".strip()
            )
            # Prefer the composite sheet (all poses in one consistent image).
            # Fall back to individual view files for projects that ran Stage 2
            # before the sheet format was introduced.
            char_ref_dir = project_dir / "refs" / cid
            sheet = char_ref_dir / "sheet.png"
            if sheet.exists():
                ref_paths.append(str(sheet))
            else:
                # Legacy: scale view count by character count to reduce duplicate
                # character risk (more refs per character → model duplicates them).
                if char_count <= 1:
                    legacy_views = ["front", "three_quarter", "gesture"]
                elif char_count == 2:
                    legacy_views = ["front", "three_quarter"]
                else:
                    legacy_views = ["front"]
                for view in legacy_views:
                    p = char_ref_dir / f"{view}.png"
                    if p.exists():
                        ref_paths.append(str(p))

    # Location anchor
    scene = next((s for s in story_bible.scenes if s.id == panel.scene_id), None)
    loc = None
    if scene:
        loc = next((loc for loc in story_bible.locations if loc.id == scene.location_id), None)
    loc_text = f"LOCATION:\n{loc.visual_anchor}" if loc else ""

    # Shot-type-specific framing instruction
    _shot_framing: dict[str, str] = {
        "close-up":      (
            "CLOSE-UP FRAMING: Face and shoulders fill the frame. "
            "Expression must be precise and physically literal — show the exact micro-expression "
            "described, not a generic version of it. Restrained, not theatrical."
        ),
        "medium":        (
            "MEDIUM SHOT: Full body visible head to toe. "
            "Character(s) occupy the lower two-thirds of the frame; environment visible above."
        ),
        "over-shoulder": (
            "OVER-SHOULDER: One character seen from behind in the foreground, "
            "the other facing camera. Camera at shoulder height. Both characters distinct."
        ),
        "wide":          (
            "WIDE SHOT: Environment dominates. Characters visible in full body "
            "with significant surrounding space. Do not crop the feet."
        ),
        "extreme-wide":  (
            "EXTREME WIDE: Establishing shot. Environment is the subject; "
            "characters are small in frame. Show the full setting."
        ),
    }
    shot_key = panel.shot_type.lower().replace(" ", "-")
    shot_instruction = _shot_framing.get(shot_key, f"Shot: {panel.shot_type}")

    # Panel direction — character count constraint is explicit and comes first
    # to prevent the model from placing duplicate instances of the same character.
    direction = (
        f"CHARACTERS IN FRAME: exactly {char_count}. "
        f"Do not duplicate any character. No cloned figures. No repeated persons.\n"
        f"{shot_instruction}\n"
        f"Camera: {panel.camera_angle}\n"
        f"Background: {panel.background_description}\n"
        f"Lighting: {panel.lighting}, Mood: {panel.mood}\n"
    )
    for cid, action in panel.character_actions.items():
        char = next((c for c in story_bible.characters if c.id == cid), None)
        name = char.name if char else cid
        expr = panel.character_expressions.get(cid, "")
        pos = panel.character_positions.get(cid, "")
        direction += f"{name}: {action}, expression: {expr}, position: {pos}\n"

    # Props — inject visual anchors for all story props so the image model
    # never has to guess what they look like.
    prop_sections: list[str] = []
    for prop in getattr(story_bible, "props", []):
        prop_sections.append(
            f"PROP ({prop.name}) — USE THIS DESCRIPTION VERBATIM WHEN THIS OBJECT APPEARS:\n"
            f"{prop.visual_anchor}"
        )

    # Per-panel dimensions derived from shot type — portrait ratios match the
    # tall narrow panels produced by the 6-panel page layout.
    w, h = _dimensions_for_shot(panel.shot_type)

    parts = [
        f"STYLE TEMPLATE:\n{config.style_template}",
        "",
        loc_text,
        "",
        "\n".join(char_sections),
        "",
        ("\n\n".join(prop_sections) + "\n") if prop_sections else "",
        f"PANEL DIRECTION:\n{direction}",
        "",
        f"REFERENCE IMAGE PATHS: {json.dumps(ref_paths)}",
        f"IMAGE DIMENSIONS: {w}x{h}",
        f"STEPS: {config.image_steps}",
        f"GUIDANCE SCALE: {config.flux_guidance_scale}",
    ]
    return "\n".join(parts)


async def _process_panel(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    panel_path: Path,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> ImagePrompt | None:
    """Generate an image prompt for a single panel."""
    panel = PanelBreakdown.model_validate_json(panel_path.read_text())

    output_dir = project_dir / "prompts" / panel.scene_id
    output_path = output_dir / f"panel_{panel.panel_number:03d}.json"
    if output_path.exists():
        return ImagePrompt.model_validate_json(output_path.read_text())

    user_content = _build_user_content(panel, story_bible, config, project_dir)

    async with semaphore:
        result = await gemini.generate_json(
            config=config,
            model=config.prompt_model,
            system_prompt=system_prompt,
            user_content=user_content,
        )

    if isinstance(result, list):
        result = result[0]
    prompt = ImagePrompt.model_validate(result)
    # The LLM may hallucinate scene_id/panel_number. Force them from the
    # actual panel file so s6 writes images to the correct paths.
    prompt.scene_id = panel.scene_id
    prompt.panel_number = panel.panel_number
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt.model_dump_json(indent=2))
    return prompt


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 5: Generate image prompts for all panels."""
    emit = on_event or _NOOP

    story_bible = _load_story_bible(project_dir)
    system_prompt = PROMPT_PATH.read_text()

    # Collect all panel files
    panels_dir = project_dir / "panels"
    panel_files: list[Path] = []
    if not panels_dir.exists():
        console.print("[red]No panels found. Run stage 4 (panels) first.[/red]")
        emit({"type": "log", "stage": "prompts", "level": "error",
              "message": "No panels found. Run stage 4 (panels) first."})
        return
    target_scenes = set(scene_ids) if scene_ids else None
    for scene_dir in sorted(panels_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        if target_scenes and scene_dir.name not in target_scenes:
            continue
        for pf in sorted(scene_dir.glob("panel_*.json")):
            panel_files.append(pf)

    begin_stage(state, "prompts", total=len(panel_files))
    emit({"type": "stage_begin", "stage": "prompts", "total": len(panel_files)})
    save_state(state, project_dir)

    semaphore = asyncio.Semaphore(config.parallel_batch_size)

    try:
        with Progress() as progress:
            task = progress.add_task("Image prompts", total=len(panel_files))
            for batch_start in range(0, len(panel_files), config.parallel_batch_size):
                batch = panel_files[batch_start:batch_start + config.parallel_batch_size]
                coros = [
                    _process_panel(config, project_dir, story_bible, pf, system_prompt, semaphore)
                    for pf in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for pf, result in zip(batch, results):
                    if isinstance(result, Exception):
                        console.print(f"[red]Failed {pf.name}: {result}[/red]")
                        emit({"type": "log", "stage": "prompts", "level": "error",
                              "message": f"Failed {pf.name}: {result}"})
                        record_item_failed(state, "prompts", str(pf))
                    else:
                        record_item_done(state, "prompts", cost=0.001)
                        emit({"type": "stage_progress", "stage": "prompts",
                              "done": state.stages["prompts"].items_done,
                              "total": state.stages["prompts"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "prompts")
        emit({"type": "stage_complete", "stage": "prompts",
              "done": state.stages["prompts"].items_done,
              "total": state.stages["prompts"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 5 complete.[/green]")

    except Exception as e:
        fail_stage(state, "prompts", str(e))
        emit({"type": "stage_fail", "stage": "prompts", "message": str(e)})
        save_state(state, project_dir)
        raise
