"""Stage 7: Image prompts → Panel images

Generates panel images using the assembled prompts and character reference
images for multi-reference consistency.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image as PILImage
from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.ai.providers.base import RefImage
from novel_to_comic.image_references import ReferencePlan, build_reference_plan
from novel_to_comic.prompt_assembly import (
    ensure_current_panel_prompt,
    ensure_layout,
    ensure_visual_brief,
    layout_pass_applies,
)
from novel_to_comic.clients import flux
from novel_to_comic.config import Config
from novel_to_comic.events import make_progress
from novel_to_comic.image_ref_strategy import RefStrategy
from novel_to_comic.layout_planning import load_layout_plan, prompt_path_for_panel, scene_panel_map
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.panel_versions import record_current_panel_version
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.panel_aspect import aspect_for_dimensions, aspect_within_tolerance, generation_shape_for_aspect
from novel_to_comic.prompting import (
    ensure_distilled_prompt,
    render_generation_prompt,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.usage import ApiResult, estimate_image_cost

log = logging.getLogger(__name__)

console = Console()


class AspectMismatchError(ValueError):
    """Raised when a provider returns an image with the wrong frame aspect."""

def _relative_to_project(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _write_generation_meta(image_path: Path, payload: dict) -> None:
    artifacts.write_asset_meta(image_path, payload)


def _write_failure_meta(image_path: Path, payload: dict) -> None:
    artifacts.write_asset_failure(image_path, payload)


def _cache_meta_projection(payload: dict) -> dict:
    projected = dict(payload)
    parameters = dict(projected.get("parameters") or {})
    parameters.pop("reference_diagnostics", None)
    projected["parameters"] = parameters
    return projected


def _asset_matches_generation_meta(output_path: Path, expected: dict) -> bool:
    if not output_path.exists():
        return False
    try:
        actual = artifacts.read_asset_meta(output_path)
    except Exception:
        return False
    return _cache_meta_projection(actual) == _cache_meta_projection(expected)


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with PILImage.open(path) as image:
            return image.width, image.height
    except Exception:
        return None, None


def _requested_prompt_aspect(prompt: ImagePrompt) -> float | None:
    return (
        getattr(prompt, "generation_aspect_ratio", None)
        or aspect_for_dimensions(getattr(prompt, "width", None), getattr(prompt, "height", None))
    )


def _meta_with_output_aspect(image_path: Path, meta_payload: dict, prompt: ImagePrompt) -> dict:
    actual_width, actual_height = _image_dimensions(image_path)
    actual_aspect = aspect_for_dimensions(actual_width, actual_height)
    requested_aspect = _requested_prompt_aspect(prompt)
    requested_shape = getattr(prompt, "generation_shape", None) or generation_shape_for_aspect(requested_aspect)
    aspect_ok = aspect_within_tolerance(actual_aspect, requested_aspect)
    updated = dict(meta_payload)
    params = dict(updated.get("parameters", {}))
    params.update({
        "requested_aspect_ratio": requested_aspect,
        "requested_shape": requested_shape,
        "actual_width": actual_width,
        "actual_height": actual_height,
        "actual_aspect_ratio": actual_aspect,
        "aspect_validation_status": "compatible" if aspect_ok else "shape_mismatch",
    })
    updated["parameters"] = params
    return updated


def _raise_if_aspect_mismatch(meta_payload: dict) -> None:
    params = meta_payload.get("parameters", {})
    if params.get("aspect_validation_status") == "shape_mismatch":
        raise AspectMismatchError(
            "shape_mismatch: generated image aspect "
            f"{params.get('actual_aspect_ratio')} does not match requested "
            f"{params.get('requested_aspect_ratio')}"
        )


def _use_continuity_refs(config: Config) -> bool:
    return getattr(config, "continuity_mode", "hybrid") in {"ref_only", "hybrid"}


def _plate_ref_path(project_dir: Path, loc_id: str, state_id: str | None) -> Path | None:
    """Return the location plate matching the panel's active state.

    Prefers the per-state plate (plates/{state_id}.png) so a panel set in a
    non-default state never gets an image reference that contradicts its text
    anchor; falls back to the location's default plate.
    """
    if state_id:
        state_plate = project_dir / "plates" / f"{state_id}.png"
        if state_plate.exists():
            return state_plate
    plate = project_dir / "plates" / f"{loc_id}.png"
    return plate if plate.exists() else None


def _prev_transition_out(prompt_path: Path, panel_number: int) -> str | None:
    """Read the previous panel's transition_out from its stored prompt."""
    prev_path = prompt_path.parent / f"panel_{panel_number - 1:03d}.json"
    if not prev_path.exists():
        return None
    try:
        return ImagePrompt.model_validate_json(prev_path.read_text()).transition_out
    except Exception:
        return None


def _interleave_by_scene(prompt_files: list[Path]) -> list[Path]:
    """Round-robin prompt files across scenes, preserving panel order per scene.

    Keeps each batch spread over several scenes so panels that DO chain on a
    predecessor (match_cut continuity) never dominate a batch. A panel's
    predecessor always sorts earlier, so event waits cannot cross batches
    backwards.
    """
    by_scene: dict[str, list[Path]] = {}
    scene_order: list[str] = []
    for pf in prompt_files:
        scene = pf.parent.name
        if scene not in by_scene:
            by_scene[scene] = []
            scene_order.append(scene)
        by_scene[scene].append(pf)
    interleaved: list[Path] = []
    round_index = 0
    while len(interleaved) < len(prompt_files):
        for scene in scene_order:
            files = by_scene[scene]
            if round_index < len(files):
                interleaved.append(files[round_index])
        round_index += 1
    return interleaved


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


def _prop_ids_from_prompt(prompt: ImagePrompt) -> list[str]:
    """Derive prop ids from a prompt's matched props.

    Slice 04: reference selection is semantic, not path-based. The prop ids
    come from the props the prompt actually matched (not stored paths). We
    recover ids from any prop ref paths the prompt carries (legacy) plus the
    props/ directory on disk keyed by the prompt's prop names.
    """
    return list(dict.fromkeys(
        anchor.entity_id
        for anchor in getattr(prompt, "anchors", []) or []
        if anchor.kind == "prop" and anchor.entity_id
    ))


def _critical_prop_ids_from_prompt(prompt: ImagePrompt) -> set[str]:
    explicit_text = " ".join([
        *(getattr(prompt, "key_objects", []) or []),
        *(getattr(prompt, "visual_requirements", []) or []),
    ]).lower()
    return {
        anchor.entity_id
        for anchor in getattr(prompt, "anchors", []) or []
        if anchor.kind == "prop"
        and anchor.entity_id
        and (
            anchor.entity_id.lower() in explicit_text
            or anchor.name.lower() in explicit_text
        )
    }


def _read_prev_panel_prompt(
    project_dir: Path, prompt: ImagePrompt, prompt_path: Path | None
) -> ImagePrompt | None:
    if prompt.panel_number <= 1:
        return None
    prev_prompt_path = (
        prompt_path.parent / f"panel_{prompt.panel_number - 1:03d}.json"
        if prompt_path is not None
        else project_dir / "direct" / prompt.scene_id / f"panel_{prompt.panel_number - 1:03d}.json"
    )
    if not prev_prompt_path.exists():
        return None
    try:
        return ImagePrompt.model_validate_json(prev_prompt_path.read_text())
    except Exception:
        return None


def _prev_subject_states(prev_prompt: ImagePrompt | None) -> dict[str, str | None]:
    """Map character_id → appearance_state_id for the previous panel's subjects."""
    if prev_prompt is None:
        return {}
    return {
        s.character_id: s.appearance_state_id
        for s in getattr(prev_prompt, "subjects", []) or []
        if s.character_id
    }


def build_panel_reference_plan(
    config: Config,
    project_dir: Path,
    prompt: ImagePrompt,
    *,
    prompt_path: Path | None = None,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    output_dir: Path | None = None,
    location_labels: dict[str, str] | None = None,
) -> ReferencePlan:
    """Build the one final, capability-aware ReferencePlan for a panel.

    Slice 04: this is the single selection owner. Candidates are resolved from
    semantic entity/state ids + the filesystem (not stored paths), the route's
    hard cap and role restrictions are applied here, and selected content
    hashes drive the selection fingerprint. No later layer selects, caps, or
    reorders references.
    """
    from novel_to_comic.image_models import image_model_profile_for_config

    route_profile = image_model_profile_for_config(config)
    prop_ids = _prop_ids_from_prompt(prompt)
    critical_prop_ids = _critical_prop_ids_from_prompt(prompt)
    primary_poses = artifacts.read_primary_refs(project_dir)
    strategy = RefStrategy.for_config(config)

    # Continuity: resolve the previous panel's subject/location state so the
    # plan can suppress an incompatible continuity ref across a state change.
    # The continuity ref is gated by the config continuity_mode AND the route's
    # capability (GPT Image 2 never uses prev-panel continuity).
    prev_prompt = _read_prev_panel_prompt(project_dir, prompt, prompt_path)
    prev_states = _prev_subject_states(prev_prompt)
    prev_loc_state = getattr(prev_prompt, "location_state_id", None) if prev_prompt else None
    continuity_enabled = (
        _use_continuity_refs(config)
        and strategy.use_prev_panel_image(getattr(prev_prompt, "transition_out", None))
    )

    # Location id: prefer the prompt's resolved location_id, fall back to the
    # scene→location map. Pass location labels through as the resolved plate's
    # label so prompts stay readable.
    loc_id = getattr(prompt, "location_id", None) or (scene_to_location or {}).get(prompt.scene_id)
    effective_scene_to_location = {prompt.scene_id: loc_id} if loc_id else {}
    plan = build_reference_plan(
        route_profile=route_profile,
        project_dir=project_dir,
        prompt=prompt,
        style_sample=style_sample,
        scene_to_location=effective_scene_to_location,
        prop_ids=prop_ids,
        critical_prop_ids=critical_prop_ids,
        primary_poses=primary_poses,
        prev_subject_states=prev_states,
        prev_location_state_id=prev_loc_state,
        continuity_enabled=continuity_enabled,
    )

    # Attach human-readable location labels to selected location plates.
    if location_labels and loc_id:
        label = location_labels.get(loc_id) or loc_id
        plan = _with_location_labels(plan, label)
    return plan


def _with_location_labels(plan: ReferencePlan, label: str) -> ReferencePlan:
    """Return a copy of the plan with location-plate assets labeled."""
    if not any(a.role == "location_plate" for a in plan.selected):
        return plan
    from novel_to_comic.image_references import ReferenceAsset

    selected = tuple(
        ReferenceAsset(
            path=a.path, role=a.role, entity_id=a.entity_id,
            appearance_state_id=a.appearance_state_id,
            authority_scope=a.authority_scope,
            preserve_facets=a.preserve_facets, ignore_facets=a.ignore_facets,
            pose=a.pose, content_sha256=a.content_sha256,
            lineage_parent_sha256=a.lineage_parent_sha256,
            label=label if a.role == "location_plate" else a.label,
        )
        for a in plan.selected
    )
    from novel_to_comic.image_references import selection_fingerprint_hex

    return ReferencePlan(
        expected_route=plan.expected_route,
        selected=selected,
        dropped=plan.dropped,
        selection_fingerprint=selection_fingerprint_hex(selected),
        warnings=plan.warnings,
    )


def resolve_panel_references(
    config: Config,
    project_dir: Path,
    prompt: ImagePrompt,
    *,
    prompt_path: Path | None = None,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    output_dir: Path | None = None,
    location_labels: dict[str, str] | None = None,
) -> list[RefImage]:
    """Return ordered, role-aware refs that a panel image request will upload.

    Slice 04: delegates to :func:`build_panel_reference_plan` (the single
    selection owner) and projects the finalized plan's selected assets into
    provider ``RefImage`` objects. No selection, capping, or reordering happens
    here.
    """
    plan = build_panel_reference_plan(
        config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
        output_dir=output_dir,
        location_labels=location_labels,
    )
    _surface_plan_warnings(plan)
    return plan.to_ref_images()


def _surface_plan_warnings(plan: ReferencePlan) -> None:
    """Log dropped-reference diagnostics so the backend surfaces them.

    UI presentation stays minimal until Slice 13; for now the diagnostics are
    visible in server logs and (via the plan) in generation metadata.
    """
    for drop in plan.dropped:
        log.warning(
            "reference_plan drop: reason=%s detail=%s",
            drop.reason.value,
            drop.detail,
        )
    for warning in plan.warnings:
        log.warning("reference_plan warning: %s", warning)


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
    scene_to_location_from_caller = scene_to_location is not None
    scene_to_location = scene_to_location or {}
    location_labels: dict[str, str] = {}
    if artifacts.story_bible_path(project_dir).exists():
        try:
            story_bible = artifacts.read_story_bible(project_dir)
            if not scene_to_location_from_caller:
                scene_to_location = {s.id: s.location_id for s in story_bible.scenes}
            location_labels = {loc.id: loc.name for loc in story_bible.locations}
        except Exception:
            scene_to_location = {}
    plan = build_panel_reference_plan(
        config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
        location_labels=location_labels,
    )
    _surface_plan_warnings(plan)
    refs = plan.to_ref_images()
    generation_prompt = render_generation_prompt(
        prompt,
        config.style_template,
        config.effective_image_model(),
        refs=refs,
    )
    return estimate_image_cost(
        config.effective_image_model(),
        1,
        quality=getattr(config, "image_quality", None),
        ref_count=plan.ref_count,
        prompt_text=generation_prompt,
    )


def _estimate_prompt_files_cost(
    config: Config,
    project_dir: Path,
    prompt_files: list[Path],
    *,
    style_sample: Path | None,
    scene_to_location: dict[str, str],
) -> float:
    """Estimate exactly the prompts selected for this run.

    This deliberately ignores output existence: retry-failed runs may target a
    panel whose previous image still exists beside failure metadata.
    """
    total = 0.0
    model = config.effective_image_model()
    quality = getattr(config, "image_quality", None)
    for prompt_path in prompt_files:
        try:
            total += estimate_panel_image_cost_usd(
                config,
                project_dir,
                prompt_path,
                style_sample=style_sample,
                scene_to_location=scene_to_location,
            )
        except Exception:
            total += estimate_image_cost(model, 1, quality=quality)
    return total


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


def _is_rate_limit_error(exc: BaseException) -> bool:
    """True when the failure is an upstream quota / rate-limit (HTTP 429).

    These are transient and prompt-independent — gemini-3-pro-image preview has
    tight quota — so they should be retried (``retry_failed``) once quota
    resets, NOT diagnosed as a prompt problem.
    """
    tokens = ("429", "resource_exhausted", "rate limit", "ratelimit", "quota")
    for node in _exception_chain(exc):
        if isinstance(getattr(node, "response", None), object):
            status = getattr(getattr(node, "response", None), "status_code", None)
            if status == 429:
                return True
        text = " ".join(
            [str(node), *(str(arg) for arg in getattr(node, "args", ()) if arg is not None)]
        ).lower()
        if any(token in text for token in tokens):
            return True
    return False


def _is_provider_blocked_error(exc: BaseException) -> bool:
    tokens = (
        "image_prohibited",
        "prohibited_content",
        "responsible ai",
        "filtered out",
        "safety rating",
        "safety_ratings",
        "safety filter",
        "block_reason",
        "blockreason",
        "finish_reason=safety",
        "finish_reason=content_filter",
        "violated google",
        "unable to show the generated image",
        "silently rejected",
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
    style_sample: Path | None,
    scene_to_location: dict[str, str],
    panel_events: dict[tuple[str, int], asyncio.Event] | None,
    story_bible: StoryBible | None,
    force: bool = False,
    ctx: StageRuntime | None = None,
) -> ApiResult[Path | None]:
    """Generate a single panel image from its prompt.

    Style / continuity refs are chosen in priority order per panel:
      - previous panel image (N-1) from the same scene when transition metadata
        indicates smooth continuity.
      - style_sample + location plate — used for non-GPT-Image primary routes
                       when a panel lacks a smooth-continuity predecessor.
                       GPT Image 2 keeps location context text-only to avoid
                       high-fidelity texture leakage from plates.

    Concurrency: panels run in parallel up to the semaphore limit. A panel
    waits for its predecessor (via panel_events) ONLY when the predecessor's
    transition would actually feed it as a continuity image ref (match_cut on
    a ref-capable model) — everything else proceeds independently.

    Subject refs (character sheets / pose crops) are always passed first to
    flux.generate_image_multi_ref so character identity gets the strongest
    positional weight in the Gemini contents list.
    """
    panel_key: tuple[str, int] | None = None
    panel_started_at: float | None = None
    output_path: Path | None = None
    meta_payload: dict | None = None
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
        if (
            prev_event
            and _use_continuity_refs(config)
            and RefStrategy.for_config(config).use_prev_panel_image(
                _prev_transition_out(prompt_path, raw_prompt.panel_number)
            )
        ):
            await prev_event.wait()

        prompt = raw_prompt
        if story_bible is not None:
            distilled_prompt = ensure_distilled_prompt(config, prompt)
            if distilled_prompt is not prompt:
                prompt = distilled_prompt
                prompt_path.write_text(prompt.model_dump_json(indent=2))
        # Backfill the prose visual brief for prompts generated before the
        # brief existed (or after an edit cleared it).
        briefed_prompt = await ensure_visual_brief(config, prompt)
        if briefed_prompt is not prompt:
            prompt = briefed_prompt
            prompt_path.write_text(prompt.model_dump_json(indent=2))
        # Backfill the region layout for layout-aware models (Reve) when the
        # prompt predates the layout pass or an edit cleared it.
        laid_out_prompt = await ensure_layout(config, prompt)
        if laid_out_prompt is not prompt:
            prompt = laid_out_prompt
            prompt_path.write_text(prompt.model_dump_json(indent=2))

        output_dir = project_dir / "draw" / prompt.scene_id
        output_path = output_dir / f"panel_{prompt.panel_number:03d}.png"

        reference_plan = build_panel_reference_plan(
            config,
            project_dir,
            prompt,
            prompt_path=prompt_path,
            style_sample=style_sample,
            scene_to_location=scene_to_location,
            location_labels=(
                {loc.id: loc.name for loc in story_bible.locations}
                if story_bible is not None
                else {}
            ),
            output_dir=output_dir,
        )
        _surface_plan_warnings(reference_plan)
        refs = reference_plan.to_ref_images()

        generation_path = output_path
        if force:
            generation_path = output_path.with_name(
                f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
            )
        generation_prompt = render_generation_prompt(
            prompt,
            config.style_template,
            config.effective_image_model(),
            refs=refs,
        )
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
                "generation_aspect_ratio": getattr(prompt, "generation_aspect_ratio", None),
                "generation_width": getattr(prompt, "generation_width", None),
                "generation_height": getattr(prompt, "generation_height", None),
                "generation_shape": getattr(prompt, "generation_shape", None),
                "generation_aspect_source": getattr(prompt, "generation_aspect_source", None),
                "steps": prompt.steps,
                "style_template": config.style_template,
                "reference_selection_fingerprint": reference_plan.selection_fingerprint,
                "refs": [
                    {
                        "path": _relative_to_project(asset.path, project_dir),
                        "role": asset.role,
                        "label": asset.label,
                        "entity_id": asset.entity_id,
                        "appearance_state_id": asset.appearance_state_id,
                        "authority_scope": asset.authority_scope.value,
                        "preserve_facets": list(asset.preserve_facets),
                        "ignore_facets": list(asset.ignore_facets),
                        "content_sha256": asset.content_sha256,
                        "lineage_parent_sha256": asset.lineage_parent_sha256,
                    }
                    for asset in reference_plan.selected
                ],
                "reference_diagnostics": {
                    "dropped": [
                        {
                            "path": _relative_to_project(drop.candidate.path, project_dir),
                            "role": drop.candidate.role,
                            "reason": drop.reason.value,
                            "detail": drop.detail,
                        }
                        for drop in reference_plan.dropped
                    ],
                    "warnings": list(reference_plan.warnings),
                },
                "continuity_note": prompt.continuity_note,
                "layout": (
                    prompt.layout.sanitized().model_dump()
                    if prompt.layout is not None and layout_pass_applies(config)
                    else None
                ),
            },
        }
        if (
            output_path.exists()
            and not force
            and not artifacts.asset_failure_path(output_path).exists()
            and _asset_matches_generation_meta(
                output_path,
                _meta_with_output_aspect(output_path, meta_payload, prompt),
            )
        ):
            return ApiResult(value=output_path, usage=None)

        if ctx is not None:
            ctx.emit_panel_start(prompt.scene_id, prompt.panel_number)
            panel_started_at = time.monotonic()

        try:
            async with semaphore:
                flux_result = await flux.generate_image_multi_ref(
                    config=config,
                    prompt=generation_prompt,
                    output_path=generation_path,
                    refs=refs,
                    width=prompt.width,
                    height=prompt.height,
                    steps=prompt.steps,
                    layout=prompt.layout if layout_pass_applies(config) else None,
                    feature="draw.panel_image",
                )
            result = flux_result.value
            if result:
                meta_payload = _meta_with_output_aspect(result, meta_payload, prompt)
                _raise_if_aspect_mismatch(meta_payload)
            if force and result:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                record_current_panel_version(
                    project_dir,
                    prompt.scene_id,
                    prompt.panel_number,
                    reason="before_regenerate",
                )
                generation_path.replace(output_path)
                tmp_echo = artifacts.asset_layout_echo_path(generation_path)
                if tmp_echo.exists():
                    tmp_echo.replace(artifacts.asset_layout_echo_path(output_path))
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
            if force:
                artifacts.asset_layout_echo_path(generation_path).unlink(missing_ok=True)

        if result:
            artifacts.asset_failure_path(output_path).unlink(missing_ok=True)
            _write_generation_meta(output_path, meta_payload)
        if ctx is not None and panel_started_at is not None:
            ctx.emit_panel_done(
                prompt.scene_id, prompt.panel_number,
                status="ok",
                duration_ms=int((time.monotonic() - panel_started_at) * 1000),
            )
        return ApiResult(value=result, usage=flux_result.usage)
    except Exception as exc:
        if output_path is not None and meta_payload is not None:
            try:
                provider_blocked = _is_provider_blocked_error(exc)
                rate_limited = not provider_blocked and _is_rate_limit_error(exc)
                failure_payload = {
                    **meta_payload,
                    "kind": "panel_image_failure",
                    "failed_at": datetime.now(UTC).isoformat(),
                    "classification": (
                        "provider_blocked"
                        if provider_blocked
                        else "rate_limited"
                        if rate_limited
                        else "shape_mismatch"
                        if isinstance(exc, AspectMismatchError)
                        else "generation_error"
                    ),
                    "recoverable": True,
                    "user_message": (
                        "The image provider blocked this panel. Edit the prompt and use Quick Re-Do "
                        "to generate replacement art before composing."
                        if provider_blocked
                        else "The image provider was rate-limited (quota exhausted). The prompt is fine — "
                        "wait for quota to reset and use Retry Failed; no prompt edit is needed."
                        if rate_limited
                        else "The image provider returned art with the wrong frame shape. Regenerate this panel before composing."
                        if isinstance(exc, AspectMismatchError)
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
        if ctx is not None and panel_started_at is not None and panel_key is not None:
            ctx.emit_panel_done(
                panel_key[0], panel_key[1],
                status="failed",
                duration_ms=int((time.monotonic() - panel_started_at) * 1000),
                error=_fmt_error(exc),
            )
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

    if story_bible is not None and artifacts.layout_plan_path(project_dir).exists():
        plan = load_layout_plan(project_dir)
        scene_panels = scene_panel_map(plan).get(scene_id, [])
        for index, panel in enumerate(scene_panels):
            if panel.panel_number != panel_number:
                continue
            prev_panel = scene_panels[index - 1] if index > 0 else None
            ensure_current_panel_prompt(config, project_dir, panel, story_bible, prev_panel)
            break

    api_result = await _generate_panel(
        config,
        project_dir,
        prompt_path,
        semaphore or asyncio.Semaphore(1),
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
    ctx: StageRuntime,
    scene_ids: list[str] | None = None,
    panel_numbers: list[int] | None = None,
    retry_failed: bool = False,
) -> None:
    """Execute the draw stage: generate panel images."""
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
                if not prompt_path_for_panel(project_dir, panel).exists():
                    continue
                prev_panel = scene_panels[index - 1] if index > 0 else None
                ensure_current_panel_prompt(config, project_dir, panel, story_bible, prev_panel)

    # ── Consistency context ───────────────────────────────────────────────────
    # 1. Global style anchor
    style_sample = _find_style_sample(project_dir, config.style_template)
    if style_sample:
        console.print(f"[dim]Style anchor: {style_sample.name}[/dim]")
    else:
        console.print("[yellow]No style sample found — run `pipeline style` and generate a sample for tighter consistency.[/yellow]")

    # 2. Scene → location mapping (for location plate lookup)
    scene_to_location: dict[str, str] = {}
    if story_bible is not None:
        scene_to_location = {s.id: s.location_id for s in story_bible.scenes}

    panel_events: dict[tuple[str, int], asyncio.Event] = {}
    for pf in prompt_files:
        try:
            panel_num = int(pf.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        panel_events[(pf.parent.name, panel_num)] = asyncio.Event()

    # Interleave scenes round-robin so a batch is not dominated by one scene —
    # match_cut chains within a scene serialize those panels, and a same-scene
    # batch would wait on itself.
    prompt_files = _interleave_by_scene(prompt_files)

    # Detect style-template drift relative to the cast plates. When the
    # template was edited after cast ran, plates no longer match the panel
    # output. Surface a warning so the user can decide whether to re-run cast.
    from novel_to_comic.state import style_template_drifted
    if style_template_drifted(ctx.state, config.style_template):
        drift_msg = (
            "Style template changed since cast plates were generated. Panel images "
            "may not match the character/location references. Consider re-running "
            "the cast stage."
        )
        console.print(f"[yellow]{drift_msg}[/yellow]")
        ctx.log(drift_msg, level="warning")

    estimated = _estimate_prompt_files_cost(
        config,
        project_dir,
        prompt_files,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
    )
    batch_size = config.effective_image_concurrency()
    semaphore = asyncio.Semaphore(batch_size)

    with ctx.execute(total=len(prompt_files), estimated_cost_usd=estimated):
        ctx.log(f"Preparing {len(prompt_files)} panel image jobs...")
        with make_progress(ctx.on_event) as progress:
            task = progress.add_task("Generating panels", total=len(prompt_files))
            for batch_start in range(0, len(prompt_files), batch_size):
                # Cost limit is checked between batches only, so a batch in
                # flight can overshoot by up to batch_size * per-image cost.
                if config.cost_limit_usd and ctx.state.total_cost_usd >= config.cost_limit_usd:
                    console.print(f"[yellow]Cost limit (${config.cost_limit_usd}) reached. Pausing.[/yellow]")
                    break

                batch = prompt_files[batch_start:batch_start + batch_size]
                first = batch_start + 1
                last = batch_start + len(batch)
                ctx.log(f"Drawing panel batch {first}-{last} of {len(prompt_files)}")
                coros = [
                    _generate_panel(config, project_dir, pf, semaphore,
                                    style_sample, scene_to_location, panel_events, story_bible,
                                    ctx=ctx)
                    for pf in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for pf, result in zip(batch, results):
                    if isinstance(result, Exception):
                        # Unwrap RetryError → actual cause → OS error
                        cause = getattr(result, "__cause__", None) or result
                        msg = f"Failed {pf.name}: {_fmt_error(cause)}"
                        console.print(f"[red]{msg}[/red]")
                        ctx.log(msg, level="error")
                        ctx.record_item_failed(f"{pf.parent.name}/{pf.stem}")
                    else:
                        ctx.record_item_done(usage=result.usage)
                        ctx.log(f"Finished {pf.parent.name} / {pf.stem.replace('_', ' ')}", level="dim")
                        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                    if task is not None:
                        progress.advance(task)
                ctx.save()

        console.print("[yellow]Draw stage complete — awaiting review.[/yellow]")
        console.print("Review generated panels in: draw/")
        console.print("Run [bold]pipeline approve --project . --stage draw[/bold] to continue.")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_image_cost

    prompts_dir = project_dir / "direct"
    if not prompts_dir.exists():
        return 0.0
    total = 0.0
    model = config.effective_image_model()
    quality = getattr(config, "image_quality", None)
    style_sample = _find_style_sample(project_dir, config.style_template)

    scene_to_location: dict[str, str] = {}
    story_bible = artifacts.read_story_bible_safe(project_dir)
    if story_bible is not None:
        scene_to_location = {scene.id: scene.location_id for scene in story_bible.scenes}

    for prompt_path in prompts_dir.glob("*/panel_*.json"):
        try:
            scene_id = prompt_path.parent.name
            panel_number = int(prompt_path.stem.split("_")[1])
        except (IndexError, ValueError):
            total += estimate_image_cost(model, 1, quality=quality)
            continue
        output_path = project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png"
        if not output_path.exists():
            try:
                total += estimate_panel_image_cost_usd(
                    config,
                    project_dir,
                    prompt_path,
                    style_sample=style_sample,
                    scene_to_location=scene_to_location,
                )
            except Exception:
                total += estimate_image_cost(model, 1, quality=quality)
    return total


STAGE = Stage(
    name="draw",
    run=run,
    outputs=lambda d: [d / "draw"],
    clean_paths=lambda d: clean_cascade(d, "draw"),
    estimate_cost=estimate_cost,
)
