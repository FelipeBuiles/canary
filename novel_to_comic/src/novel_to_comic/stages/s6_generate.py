"""Stage 6: Image prompts → Panel images via FLUX.2 Pro.

Generates panel images using the assembled prompts and character reference
images for multi-reference consistency.
"""

import asyncio
import json
import uuid
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from novel_to_comic.clients import flux
from novel_to_comic.clients.flux import _is_gemini_native, is_rate_limited_error
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import IMAGE_PROMPT_VERSION, build_image_prompt_spec, render_generation_prompt
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

COST_PER_IMAGE = 0.03  # FLUX.2 Pro via Together AI
_RATE_LIMIT_RECOVERY_COOLDOWN_SECONDS = 45.0

_HARD_CUTS = ("smash cut", "fade to", "cut to", "scene change", "time jump")
_SOFT_CONTINUITY = {"smooth_continuation", "match_cut"}


def _should_use_prev_panel_image(prev_panel: PanelBreakdown | None) -> bool:
    """Return True if the previous panel's image should be used as a style reference.

    Hard cuts (smash cut, fade to, cut to, scene change, time jump) can make the
    previous panel image actively harmful — the model might blend the previous scene
    into the new one. Only use the previous panel image for smooth transitions.
    """
    if not prev_panel:
        return False
    transition_type = (prev_panel.transition_type or "").strip().lower()
    if transition_type in _SOFT_CONTINUITY:
        return True
    if transition_type == "hard_cut":
        return False
    transition = (prev_panel.transition_note or "").lower()
    if any(hard in transition for hard in _HARD_CUTS):
        return False
    return True


def _find_style_sample(project_dir: Path, style_template: str) -> Path | None:
    """Return the sample image matching the active style template."""
    suggestions_path = project_dir / "samples" / "style_suggestions.json"
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            for i, s in enumerate(data.get("suggestions", []), 1):
                if isinstance(s, dict) and s.get("template", "").strip() == style_template.strip():
                    candidate = project_dir / "samples" / f"style_{i}.png"
                    if candidate.exists():
                        return candidate
        except Exception:
            pass
    return None


def _load_or_upgrade_prompt(
    config: Config,
    project_dir: Path,
    prompt_path: Path,
    story_bible: StoryBible | None,
    prev_panel: PanelBreakdown | None = None,
) -> ImagePrompt:
    prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    if getattr(prompt, "prompt_version", 1) >= IMAGE_PROMPT_VERSION or story_bible is None:
        return prompt

    panel_path = project_dir / "panels" / prompt.scene_id / f"panel_{prompt.panel_number:03d}.json"
    if not panel_path.exists():
        return prompt

    panel = PanelBreakdown.model_validate_json(panel_path.read_text())
    upgraded = build_image_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
    prompt_path.write_text(upgraded.model_dump_json(indent=2))
    return upgraded


def _fmt_error(exc: BaseException) -> str:
    """Return a useful one-line error string by walking the full exception chain.

    httpx.ConnectError wraps httpcore.ConnectError which wraps the OS error —
    every layer has an empty str() until you reach the root cause.  Walking
    the full __cause__ / __context__ chain finds the first non-empty message
    so the user sees something like:
        ConnectError → ConnectionRefusedError: [Errno 61] Connection refused
    instead of a blank ``ConnectError → ConnectError``.
    """
    # Build the full chain (guard against cycles)
    chain: list[BaseException] = []
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        chain.append(node)
        node = getattr(node, "__cause__", None) or getattr(node, "__context__", None)

    # Find the first entry that has a non-empty string representation
    for entry in chain:
        msg = str(entry)
        if msg:
            if entry is exc:
                return f"{type(entry).__name__}: {msg}"
            return f"{type(exc).__name__} → {type(entry).__name__}: {msg}"

    # Every exception in the chain has an empty str() — show type chain + args
    type_chain = " → ".join(type(e).__name__ for e in chain)
    for entry in chain:
        if entry.args:
            return f"{type_chain}: {entry.args[0]!r}"
    return type_chain


async def _generate_panel(
    config: Config,
    project_dir: Path,
    prompt_path: Path,
    semaphore: asyncio.Semaphore,
    scene_locks: dict[str, asyncio.Lock],
    style_sample: Path | None,
    scene_to_location: dict[str, str],
    scene_anchors: dict[str, Path],
    story_bible: StoryBible | None,
    force: bool = False,
) -> Path | None:
    """Generate a single panel image from its prompt.

    Style / continuity refs are chosen in priority order per panel:
      - scene anchor — a previously-rendered panel from the same scene. Once
                       available it supersedes style_sample + plate because it
                       already carries style, characters, and environment from
                       the same scene.
      - style_sample — global style anchor, used only for the first panel of
                       each scene.
      - location plate — environment anchor, paired with style_sample for the
                         first panel only.

    Subject refs (character sheets / pose crops) are always passed first to
    flux.generate_image_multi_ref so character identity gets the strongest
    positional weight in the Gemini contents list.
    """
    raw_prompt = ImagePrompt.model_validate_json(prompt_path.read_text())

    prev_panel: PanelBreakdown | None = None
    if raw_prompt.panel_number > 1:
        prev_panel_path = project_dir / "panels" / raw_prompt.scene_id / f"panel_{raw_prompt.panel_number - 1:03d}.json"
        if prev_panel_path.exists():
            try:
                prev_panel = PanelBreakdown.model_validate_json(prev_panel_path.read_text())
            except Exception:
                pass

    prompt = _load_or_upgrade_prompt(config, project_dir, prompt_path, story_bible, prev_panel)

    output_dir = project_dir / "images" / prompt.scene_id
    output_path = output_dir / f"panel_{prompt.panel_number:03d}.png"
    scene_lock = scene_locks.setdefault(prompt.scene_id, asyncio.Lock())

    async with scene_lock:
        if output_path.exists() and not force:
            scene_anchors[prompt.scene_id] = output_path
            return output_path

        # Subject refs: character reference sheets
        subject_refs = [Path(p) for p in prompt.reference_image_paths if Path(p).exists()]

        # Style / continuity refs: deduped by priority.
        # Once a scene anchor exists, it carries style + characters + environment
        # from the same scene, so it supersedes the global style sample and location
        # plate. HOWEVER, we skip the scene anchor if the previous panel had a hard
        # cut transition (smash cut, fade, etc.) to avoid blending scenes.
        style_refs: list[Path] = []
        scene_anchor = scene_anchors.get(prompt.scene_id)

        if scene_anchor and scene_anchor.exists():
            prev_panel_path = project_dir / "panels" / prompt.scene_id / f"panel_{prompt.panel_number - 1:03d}.json"
            prev_panel: PanelBreakdown | None = None
            if prev_panel_path.exists():
                try:
                    prev_panel = PanelBreakdown.model_validate_json(prev_panel_path.read_text())
                except Exception:
                    pass

            if _should_use_prev_panel_image(prev_panel):
                style_refs.append(scene_anchor)

        if not style_refs:
            if style_sample and style_sample.exists():
                style_refs.append(style_sample)
            loc_id = scene_to_location.get(prompt.scene_id)
            if loc_id:
                plate = project_dir / "plates" / f"{loc_id}.png"
                if plate.exists():
                    style_refs.append(plate)

        generation_path = output_path
        if force:
            generation_path = output_path.with_name(
                f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
            )

        try:
            async with semaphore:
                result = await flux.generate_image_multi_ref(
                    config=config,
                    prompt=render_generation_prompt(prompt, config.style_template),
                    output_path=generation_path,
                    reference_paths=subject_refs,
                    style_refs=style_refs or None,
                    width=prompt.width,
                    height=prompt.height,
                    steps=prompt.steps,
                )
            if force and result:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                generation_path.replace(output_path)
                result = output_path
        finally:
            if force and generation_path.exists():
                generation_path.unlink(missing_ok=True)

        # Register as scene anchor after each successful generation
        # This ensures later panels chain to the immediately previous panel
        if result:
            scene_anchors[prompt.scene_id] = output_path

        return result


async def regenerate_panel_image(
    config: Config,
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    semaphore: asyncio.Semaphore | None = None,
) -> Path | None:
    """Regenerate one panel without mutating stage counters or deleting the old image."""
    prompt_path = project_dir / "prompts" / scene_id / f"panel_{panel_number:03d}.json"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {scene_id}/panel_{panel_number:03d}")

    style_sample = _find_style_sample(project_dir, config.style_template)

    scene_to_location: dict[str, str] = {}
    story_bible: StoryBible | None = None
    bible_path = project_dir / "story_bible.json"
    if bible_path.exists():
        story_bible = StoryBible.model_validate_json(bible_path.read_text())
        scene_to_location = {s.id: s.location_id for s in story_bible.scenes}

    scene_anchors: dict[str, Path] = {}
    scene_locks: dict[str, asyncio.Lock] = {}
    images_dir = project_dir / "images"
    target_path = images_dir / scene_id / f"panel_{panel_number:03d}.png"
    if images_dir.exists():
        for scene_dir in sorted(images_dir.iterdir()):
            if scene_dir.is_dir():
                existing = [p for p in sorted(scene_dir.glob("panel_*.png")) if p != target_path]
                if existing:
                    scene_anchors[scene_dir.name] = existing[-1]

    return await _generate_panel(
        config,
        project_dir,
        prompt_path,
        semaphore or asyncio.Semaphore(1),
        scene_locks,
        style_sample,
        scene_to_location,
        scene_anchors,
        story_bible,
        force=True,
    )


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    panel_numbers: list[int] | None = None,
    retry_failed: bool = False,
    on_event: EventCallback | None = None,
) -> None:
    """Execute Stage 6: Generate panel images."""
    emit = on_event or _NOOP
    prompts_dir = project_dir / "prompts"
    prompt_files: list[Path] = []

    target_scenes = set(scene_ids) if scene_ids else None
    target_panels = set(panel_numbers) if panel_numbers else None
    if prompts_dir.exists():
        for scene_dir in sorted(prompts_dir.iterdir()):
            if not scene_dir.is_dir():
                continue
            if target_scenes and scene_dir.name not in target_scenes:
                continue
            for pf in sorted(scene_dir.glob("panel_*.json")):
                if target_panels:
                    try:
                        panel_num = int(pf.stem.split("_")[1])
                    except (IndexError, ValueError):
                        pass
                    else:
                        if panel_num not in target_panels:
                            continue
                if retry_failed:
                    # Include only panels whose output image is actually missing.
                    # More reliable than the items_failed list, which resets each run.
                    prompt = ImagePrompt.model_validate_json(pf.read_text())
                    out = project_dir / "images" / prompt.scene_id / f"panel_{prompt.panel_number:03d}.png"
                    if out.exists():
                        continue
                prompt_files.append(pf)

    # ── Consistency context ───────────────────────────────────────────────────
    # 1. Global style anchor
    style_sample = _find_style_sample(project_dir, config.style_template)
    if style_sample:
        console.print(f"[dim]Style anchor: {style_sample.name}[/dim]")
    else:
        console.print("[yellow]No style sample found — run `pipeline style` and generate a sample for tighter consistency.[/yellow]")

    # 2. Scene → location mapping (for location plate lookup)
    scene_to_location: dict[str, str] = {}
    story_bible: StoryBible | None = None
    bible_path = project_dir / "story_bible.json"
    if bible_path.exists():
        story_bible = StoryBible.model_validate_json(bible_path.read_text())
        scene_to_location = {s.id: s.location_id for s in story_bible.scenes}

    # 3. Scene anchor pool — pre-populate with already-generated panels so
    #    re-runs and retry-failed runs benefit from existing generations.
    #    Use the LAST panel in sorted order (most recently generated).
    scene_anchors: dict[str, Path] = {}
    scene_locks: dict[str, asyncio.Lock] = {}
    images_dir = project_dir / "images"
    if images_dir.exists():
        for scene_dir in sorted(images_dir.iterdir()):
            if scene_dir.is_dir():
                existing = sorted(scene_dir.glob("panel_*.png"))
                if existing:
                    scene_anchors[scene_dir.name] = existing[-1]

    # Always reset counters for clean tracking
    begin_stage(state, "generate", total=len(prompt_files))
    emit({"type": "stage_begin", "stage": "generate", "total": len(prompt_files)})
    emit({"type": "log", "stage": "generate", "level": "info",
          "message": f"Preparing {len(prompt_files)} panel image jobs..."})
    save_state(state, project_dir)

    # Google Gemini image models have tight per-minute quotas and are called
    # sequentially with a delay. Together AI supports real parallelism.
    model = config.image_model
    fallback = getattr(config, "fallback_image_model", "")
    using_google = (
        _is_gemini_native(model) or _is_gemini_native(fallback)
    )
    batch_size = 1 if using_google else config.effective_image_concurrency(google_model=False)
    inter_request_delay = 4.0 if using_google and not config.dev_mode else 0.0

    semaphore = asyncio.Semaphore(batch_size)

    try:
        with make_progress(on_event) as progress:
            task = progress.add_task("Generating panels", total=len(prompt_files))
            for batch_start in range(0, len(prompt_files), batch_size):
                # Check cost limit
                if config.cost_limit_usd and state.total_cost_usd >= config.cost_limit_usd:
                    console.print(f"[yellow]Cost limit (${config.cost_limit_usd}) reached. Pausing.[/yellow]")
                    break

                batch = prompt_files[batch_start:batch_start + batch_size]
                first = batch_start + 1
                last = batch_start + len(batch)
                emit({"type": "log", "stage": "generate", "level": "info",
                      "message": f"Drawing panel batch {first}-{last} of {len(prompt_files)}"})
                coros = [
                    _generate_panel(config, project_dir, pf, semaphore, scene_locks,
                                    style_sample, scene_to_location, scene_anchors, story_bible)
                    for pf in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for pf, result in zip(batch, results):
                    if isinstance(result, Exception):
                        recovered = False
                        if using_google and is_rate_limited_error(result):
                            msg = (
                                f"Rate limited while drawing {pf.name}; waiting "
                                f"{int(_RATE_LIMIT_RECOVERY_COOLDOWN_SECONDS)}s and retrying once."
                            )
                            console.print(f"[yellow]{msg}[/yellow]")
                            emit({"type": "log", "stage": "generate", "level": "warning", "message": msg})
                            await asyncio.sleep(_RATE_LIMIT_RECOVERY_COOLDOWN_SECONDS)
                            retry_result = await asyncio.gather(
                                _generate_panel(
                                    config,
                                    project_dir,
                                    pf,
                                    semaphore,
                                    scene_locks,
                                    style_sample,
                                    scene_to_location,
                                    scene_anchors,
                                    story_bible,
                                ),
                                return_exceptions=True,
                            )
                            retry_outcome = retry_result[0]
                            if not isinstance(retry_outcome, Exception):
                                record_item_done(state, "generate", cost=COST_PER_IMAGE)
                                emit({
                                    "type": "log",
                                    "stage": "generate",
                                    "level": "dim",
                                    "message": f"Recovered {pf.parent.name} / {pf.stem.replace('_', ' ')} after cooldown retry",
                                })
                                emit({"type": "stage_progress", "stage": "generate",
                                      "done": state.stages["generate"].items_done,
                                      "total": state.stages["generate"].items_total})
                                recovered = True
                            else:
                                result = retry_outcome
                        if recovered:
                            progress.advance(task)
                            save_state(state, project_dir)
                            continue
                        # Unwrap RetryError → actual cause → OS error
                        cause = getattr(result, "__cause__", None) or result
                        msg = f"Failed {pf.name}: {_fmt_error(cause)}"
                        console.print(f"[red]{msg}[/red]")
                        emit({"type": "log", "stage": "generate", "level": "error",
                              "message": msg})
                        record_item_failed(state, "generate", str(pf))
                    else:
                        record_item_done(state, "generate", cost=COST_PER_IMAGE)
                        emit({"type": "log", "stage": "generate", "level": "dim",
                              "message": f"Finished {pf.parent.name} / {pf.stem.replace('_', ' ')}"})
                        emit({"type": "stage_progress", "stage": "generate",
                              "done": state.stages["generate"].items_done,
                              "total": state.stages["generate"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

                if inter_request_delay and batch_start + batch_size < len(prompt_files):
                    await asyncio.sleep(inter_request_delay)

        complete_stage(state, "generate")
        emit({"type": "stage_complete", "stage": "generate",
              "done": state.stages["generate"].items_done,
              "total": state.stages["generate"].items_total})
        save_state(state, project_dir)
        console.print("[yellow]Stage 6 complete — awaiting review.[/yellow]")
        console.print("Review generated panels in: images/")
        console.print("Run [bold]pipeline approve --project . --stage generate[/bold] to continue.")

    except Exception as e:
        fail_stage(state, "generate", str(e))
        emit({"type": "stage_fail", "stage": "generate", "message": str(e)})
        save_state(state, project_dir)
        raise
