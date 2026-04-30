"""Stage 6: Image prompts → Panel images

Generates panel images using the assembled prompts and character reference
images for multi-reference consistency.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.clients import flux
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.layout_planning import load_layout_plan, prompt_path_for_panel, scene_panel_map
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.panel_versions import record_current_panel_version
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import IMAGE_PROMPT_VERSION, _SOFT_CONTINUITY, build_planned_panel_prompt_spec, render_generation_prompt
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    record_item_failed,
    save_state,
)
from novel_to_comic.usage import ApiResult, estimate_image_cost

console = Console()

def _relative_to_project(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _write_generation_meta(image_path: Path, payload: dict) -> None:
    artifacts.write_asset_meta(image_path, payload)


def _write_failure_meta(image_path: Path, payload: dict) -> None:
    artifacts.write_asset_failure(image_path, payload)


def _should_use_prev_panel_image(prev_transition_type: str | None) -> bool:
    """Return True if the previous panel's image should be used as a style reference.

    Hard cuts (smash cut, fade to, cut to, scene change, time jump) can make the
    previous panel image actively harmful — the model might blend the previous scene
    into the new one. Only use the previous panel image for smooth transitions.
    """
    if not prev_transition_type:
        return False
    transition_type = (prev_transition_type or "").strip().lower()
    if transition_type in _SOFT_CONTINUITY:
        return True
    return False


def _use_continuity_refs(config: Config) -> bool:
    return getattr(config, "continuity_mode", "hybrid") in {"ref_only", "hybrid"}


def _find_style_sample(project_dir: Path, style_template: str) -> Path | None:
    """Return the sample image matching the active style template."""
    suggestions_path = artifacts.style_suggestions_path(project_dir)
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            for i, s in enumerate(data.get("suggestions", []), 1):
                if isinstance(s, dict) and s.get("template", "").strip() == style_template.strip():
                    candidate = artifacts.style_sample_path(project_dir, i)
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
    planned_panel=None,
    prev_planned_panel=None,
) -> ImagePrompt:
    prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    if (
        getattr(prompt, "prompt_version", 1) >= IMAGE_PROMPT_VERSION
        and getattr(prompt, "planned_panel_id", None)
    ) or story_bible is None:
        return prompt

    if planned_panel is None:
        return prompt

    upgraded = build_planned_panel_prompt_spec(
        config, project_dir, planned_panel, story_bible, prev_planned_panel
    )
    prompt_path.write_text(upgraded.model_dump_json(indent=2))
    return upgraded


def resolve_panel_reference_paths(
    config: Config,
    project_dir: Path,
    prompt: ImagePrompt,
    *,
    prompt_path: Path | None = None,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    output_dir: Path | None = None,
) -> tuple[list[Path], list[Path]]:
    """Return the subject and style refs that a panel image request will upload."""
    subject_refs = [
        resolved
        for p in prompt.reference_image_paths
        if (resolved := (project_dir / p) if not Path(p).is_absolute() else Path(p)).exists()
    ]

    style_refs: list[Path] = []
    resolved_output_dir = output_dir or project_dir / "draw" / prompt.scene_id
    if _use_continuity_refs(config) and prompt.panel_number > 1:
        prev_image = resolved_output_dir / f"panel_{prompt.panel_number - 1:03d}.png"
        prev_prompt_path = (
            prompt_path.parent / f"panel_{prompt.panel_number - 1:03d}.json"
            if prompt_path is not None
            else project_dir / "direct" / prompt.scene_id / f"panel_{prompt.panel_number - 1:03d}.json"
        )
        prev_prompt = None
        if prev_prompt_path.exists():
            try:
                prev_prompt = ImagePrompt.model_validate_json(prev_prompt_path.read_text())
            except Exception:
                prev_prompt = None
        if prev_image.exists() and _should_use_prev_panel_image(getattr(prev_prompt, "transition_out", None)):
            style_refs.append(prev_image)

    if not style_refs:
        if style_sample and style_sample.exists():
            style_refs.append(style_sample)
        loc_id = (scene_to_location or {}).get(prompt.scene_id)
        if loc_id:
            plate = project_dir / "plates" / f"{loc_id}.png"
            if plate.exists():
                style_refs.append(plate)

    return subject_refs, style_refs


def estimate_panel_image_cost_usd(
    config: Config,
    project_dir: Path,
    prompt_path: Path,
    *,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
) -> float:
    """Estimate one panel image request using the same refs the draw stage uploads."""
    prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    if style_sample is None:
        style_sample = _find_style_sample(project_dir, config.style_template)
    if scene_to_location is None:
        scene_to_location = {}
        if artifacts.story_bible_path(project_dir).exists():
            try:
                story_bible = artifacts.read_story_bible(project_dir)
                scene_to_location = {s.id: s.location_id for s in story_bible.scenes}
            except Exception:
                scene_to_location = {}
    subject_refs, style_refs = resolve_panel_reference_paths(
        config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
    )
    return estimate_image_cost(
        config.effective_image_model(),
        1,
        quality=getattr(config, "image_quality", None),
        ref_count=len(subject_refs) + len(style_refs),
    )


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


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        chain.append(node)
        node = getattr(node, "__cause__", None) or getattr(node, "__context__", None)
    return chain


def _is_provider_blocked_error(exc: BaseException) -> bool:
    tokens = (
        "image_prohibited",
        "prohibited_content",
        "responsible ai",
        "filtered out",
        "safety rating",
        "safety_ratings",
        "violated google",
        "unable to show the generated image",
    )
    chain_text = " ".join(
        " ".join([str(node), *(str(arg) for arg in getattr(node, "args", ()) if arg is not None)]).lower()
        for node in _exception_chain(exc)
    )
    return any(token in chain_text for token in tokens)


async def _generate_panel(
    config: Config,
    project_dir: Path,
    prompt_path: Path,
    semaphore: asyncio.Semaphore,
    scene_locks: dict[str, asyncio.Lock],
    style_sample: Path | None,
    scene_to_location: dict[str, str],
    panel_events: dict[tuple[str, int], asyncio.Event] | None,
    story_bible: StoryBible | None,
    force: bool = False,
) -> ApiResult[Path | None]:
    """Generate a single panel image from its prompt.

    Style / continuity refs are chosen in priority order per panel:
      - previous panel image (N-1) from the same scene when transition metadata
        indicates smooth continuity.
      - style_sample + location plate — used for any panel that lacks a
                       smooth-continuity predecessor (not only the first panel).

    Subject refs (character sheets / pose crops) are always passed first to
    flux.generate_image_multi_ref so character identity gets the strongest
    positional weight in the Gemini contents list.
    """
    panel_key: tuple[str, int] | None = None
    try:
        try:
            panel_key = (prompt_path.parent.name, int(prompt_path.stem.split("_")[1]))
        except (IndexError, ValueError):
            panel_key = None

        raw_prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
        panel_key = (raw_prompt.scene_id, raw_prompt.panel_number)
        prev_event: asyncio.Event | None = None
        if panel_events and raw_prompt.panel_number > 1:
            prev_event = panel_events.get((raw_prompt.scene_id, raw_prompt.panel_number - 1))
        if prev_event:
            await prev_event.wait()

        prompt = _load_or_upgrade_prompt(config, project_dir, prompt_path, story_bible)

        output_dir = project_dir / "draw" / prompt.scene_id
        output_path = output_dir / f"panel_{prompt.panel_number:03d}.png"
        scene_lock = scene_locks.setdefault(prompt.scene_id, asyncio.Lock())

        async with scene_lock:
            if output_path.exists() and not force:
                return ApiResult(value=output_path, usage=None)

            subject_refs, style_refs = resolve_panel_reference_paths(
                config,
                project_dir,
                prompt,
                prompt_path=prompt_path,
                style_sample=style_sample,
                scene_to_location=scene_to_location,
                output_dir=output_dir,
            )

            generation_path = output_path
            if force:
                generation_path = output_path.with_name(
                    f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
                )
            generation_prompt = render_generation_prompt(prompt, config.style_template)
            meta_payload = {
                "version": 1,
                "kind": "panel_image",
                "prompt": generation_prompt,
                "prompt_sha256": hashlib.sha256(generation_prompt.encode("utf-8")).hexdigest(),
                "parameters": {
                    "planned_panel_id": prompt.planned_panel_id,
                    "scene_id": prompt.scene_id,
                    "panel_number": prompt.panel_number,
                    "image_model": config.effective_image_model(),
                    "width": prompt.width,
                    "height": prompt.height,
                    "steps": prompt.steps,
                    "style_template": config.style_template,
                    "subject_refs": [_relative_to_project(p, project_dir) for p in subject_refs],
                    "style_refs": [_relative_to_project(p, project_dir) for p in style_refs],
                    "continuity_note": prompt.continuity_note,
                },
            }

            try:
                async with semaphore:
                    flux_result = await flux.generate_image_multi_ref(
                        config=config,
                        prompt=generation_prompt,
                        output_path=generation_path,
                        reference_paths=subject_refs,
                        style_refs=style_refs or None,
                        width=prompt.width,
                        height=prompt.height,
                        steps=prompt.steps,
                        feature="draw.panel_image",
                    )
                result = flux_result.value
                if force and result:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    record_current_panel_version(
                        project_dir,
                        prompt.scene_id,
                        prompt.panel_number,
                        reason="before_regenerate",
                    )
                    generation_path.replace(output_path)
                    record_current_panel_version(
                        project_dir,
                        prompt.scene_id,
                        prompt.panel_number,
                        reason="regenerate",
                    )
                    result = output_path
            finally:
                if force and generation_path.exists():
                    generation_path.unlink(missing_ok=True)

            if result:
                artifacts.asset_failure_path(output_path).unlink(missing_ok=True)
                try:
                    _write_generation_meta(output_path, meta_payload)
                except Exception:
                    pass
            return ApiResult(value=result, usage=flux_result.usage)
    except Exception as exc:
        if "output_path" in locals() and "meta_payload" in locals():
            try:
                provider_blocked = _is_provider_blocked_error(exc)
                failure_payload = {
                    **meta_payload,
                    "kind": "panel_image_failure",
                    "failed_at": datetime.now(UTC).isoformat(),
                    "classification": "provider_blocked" if provider_blocked else "generation_error",
                    "recoverable": True,
                    "user_message": (
                        "The image provider blocked this panel. Edit the prompt and use Quick Re-Do "
                        "to generate replacement art before composing."
                        if provider_blocked
                        else "Image generation failed. Review the model error, edit the prompt if needed, and use Quick Re-Do."
                    ),
                    "error": {
                        "type": type(exc).__name__,
                        "message": _fmt_error(exc),
                        "chain": [
                            {
                                "type": type(node).__name__,
                                "message": str(node),
                                "args": [str(arg) for arg in getattr(node, "args", ())],
                            }
                            for node in _exception_chain(exc)
                        ],
                    },
                }
                _write_failure_meta(output_path, failure_payload)
            except Exception:
                pass
        raise
    finally:
        if panel_events and panel_key:
            event = panel_events.get(panel_key)
            if event:
                event.set()


async def regenerate_panel_image(
    config: Config,
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path | None]:
    """Regenerate one panel without mutating stage counters or deleting the old image."""
    prompt_path = project_dir / "direct" / scene_id / f"panel_{panel_number:03d}.json"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {scene_id}/panel_{panel_number:03d}")

    style_sample = _find_style_sample(project_dir, config.style_template)

    scene_to_location: dict[str, str] = {}
    story_bible: StoryBible | None = None
    if artifacts.story_bible_path(project_dir).exists():
        story_bible = artifacts.read_story_bible(project_dir)
        scene_to_location = {s.id: s.location_id for s in story_bible.scenes}

    scene_locks: dict[str, asyncio.Lock] = {}

    api_result = await _generate_panel(
        config,
        project_dir,
        prompt_path,
        semaphore or asyncio.Semaphore(1),
        scene_locks,
        style_sample,
        scene_to_location,
        None,
        story_bible,
        force=True,
    )
    return api_result


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
    prompts_dir = project_dir / "direct"
    prompt_files: list[Path] = []
    story_bible: StoryBible | None = None
    plan = None
    panels_by_scene = {}
    plan_path = project_dir / "plan" / "layout_plan.json"
    if plan_path.exists():
        plan = load_layout_plan(project_dir)
        panels_by_scene = scene_panel_map(plan)

    target_panels = set(panel_numbers) if panel_numbers else None
    if prompts_dir.exists():
        all_scene_dirs = sorted(d for d in prompts_dir.iterdir() if d.is_dir())
        if scene_ids:
            all_scene_dirs = [d for d in all_scene_dirs if d.name in set(scene_ids)]
        elif config.dev_mode:
            all_scene_dirs = all_scene_dirs[:1]
        for scene_dir in all_scene_dirs:
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
                    # Include panels with explicit failure metadata even if a previous
                    # successful image still exists on disk.
                    prompt = ImagePrompt.model_validate_json(pf.read_text())
                    out = project_dir / "draw" / prompt.scene_id / f"panel_{prompt.panel_number:03d}.png"
                    if out.exists() and not artifacts.asset_failure_path(out).exists():
                        continue
                prompt_files.append(pf)

    if artifacts.story_bible_path(project_dir).exists():
        story_bible = artifacts.read_story_bible(project_dir)

    if story_bible is not None and plan is not None:
        for scene_panels in panels_by_scene.values():
            for index, panel in enumerate(scene_panels):
                prompt_path = prompt_path_for_panel(project_dir, panel)
                if not prompt_path.exists():
                    continue
                prev_panel = scene_panels[index - 1] if index > 0 else None
                existing = ImagePrompt.model_validate_json(prompt_path.read_text())
                if getattr(existing, "planned_panel_id", None) == panel.panel_id and getattr(existing, "prompt_version", 1) >= IMAGE_PROMPT_VERSION:
                    continue
                upgraded = build_planned_panel_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
                prompt_path.write_text(upgraded.model_dump_json(indent=2))

    # ── Consistency context ───────────────────────────────────────────────────
    # 1. Global style anchor
    style_sample = _find_style_sample(project_dir, config.style_template)
    if style_sample:
        console.print(f"[dim]Style anchor: {style_sample.name}[/dim]")
    else:
        console.print("[yellow]No style sample found — run `pipeline style` and generate a sample for tighter consistency.[/yellow]")

    # 2. Scene → location mapping (for location plate lookup)
    scene_to_location: dict[str, str] = {}
    if artifacts.story_bible_path(project_dir).exists():
        story_bible = artifacts.read_story_bible(project_dir)
        scene_to_location = {s.id: s.location_id for s in story_bible.scenes}

    scene_locks: dict[str, asyncio.Lock] = {}
    panel_events: dict[tuple[str, int], asyncio.Event] = {}
    for pf in prompt_files:
        try:
            panel_num = int(pf.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        panel_events[(pf.parent.name, panel_num)] = asyncio.Event()

    estimated = estimate_image_cost(config.effective_image_model(), len(prompt_files), quality=getattr(config, "image_quality", None))
    begin_stage(state, "draw", total=len(prompt_files), estimated_cost_usd=estimated)
    emit({"type": "stage_begin", "stage": "draw", "total": len(prompt_files)})
    emit({"type": "log", "stage": "draw", "level": "info",
          "message": f"Preparing {len(prompt_files)} panel image jobs..."})
    save_state(state, project_dir)

    batch_size = config.effective_image_concurrency(google_model=False)

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
                emit({"type": "log", "stage": "draw", "level": "info",
                      "message": f"Drawing panel batch {first}-{last} of {len(prompt_files)}"})
                coros = [
                    _generate_panel(config, project_dir, pf, semaphore, scene_locks,
                                    style_sample, scene_to_location, panel_events, story_bible)
                    for pf in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for pf, result in zip(batch, results):
                    if isinstance(result, Exception):
                        # Unwrap RetryError → actual cause → OS error
                        cause = getattr(result, "__cause__", None) or result
                        msg = f"Failed {pf.name}: {_fmt_error(cause)}"
                        console.print(f"[red]{msg}[/red]")
                        emit({"type": "log", "stage": "draw", "level": "error",
                              "message": msg})
                        record_item_failed(state, "draw", f"{pf.parent.name}/{pf.stem}")
                    else:
                        record_item_done(state, "draw", usage=result.usage)
                        emit({"type": "log", "stage": "draw", "level": "dim",
                              "message": f"Finished {pf.parent.name} / {pf.stem.replace('_', ' ')}"})
                        emit({"type": "stage_progress", "stage": "draw",
                              "done": state.stages["draw"].items_done,
                              "total": state.stages["draw"].items_total})
                    progress.advance(task)
                save_state(state, project_dir)

        complete_stage(state, "draw")
        emit({"type": "stage_complete", "stage": "draw",
              "done": state.stages["draw"].items_done,
              "total": state.stages["draw"].items_total})
        save_state(state, project_dir)
        console.print("[yellow]Stage 7 complete — awaiting review.[/yellow]")
        console.print("Review generated panels in: images/")
        console.print("Run [bold]pipeline approve --project . --stage generate[/bold] to continue.")

    except Exception as e:
        fail_stage(state, "draw", str(e))
        emit({"type": "stage_fail", "stage": "draw", "message": str(e)})
        save_state(state, project_dir)
        raise
