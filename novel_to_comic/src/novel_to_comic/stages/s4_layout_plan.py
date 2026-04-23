"""Stage 4: Screenplay -> LayoutPlan JSON.

Phase 1 introduces a planner-owned artifact without changing downstream
stages yet. The current planner is deterministic and heuristic-driven:
it creates one planned panel per screenplay beat, then paginates those
panels scene-by-scene using the configured max panels per page.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rich.console import Console

from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.models.layout_plan import (
    LayoutPlan,
    LayoutPlanBeatRef,
    LayoutPlanMetadata,
    PanelGeometry,
    PlannedPage,
    PlannedPanel,
)
from novel_to_comic.models.panel import DialogueLine, Screenplay, ScreenplayBeat
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    save_state,
)

console = Console()


def _load_story_bible(project_dir: Path) -> StoryBible:
    return StoryBible.model_validate_json((project_dir / "story_bible.json").read_text())


def _load_screenplay(project_dir: Path, scene_id: str) -> Screenplay:
    path = project_dir / "screenplays" / f"{scene_id}.json"
    return Screenplay.model_validate_json(path.read_text())


def _screenplay_hash(screenplays: list[Screenplay]) -> str:
    digest = hashlib.sha256()
    for screenplay in screenplays:
        digest.update(screenplay.model_dump_json(exclude_none=True).encode("utf-8"))
    return digest.hexdigest()


def _beat_id(scene_id: str, beat_index: int) -> str:
    return f"{scene_id}:beat_{beat_index:03d}"


def _panel_id(scene_id: str, panel_index: int) -> str:
    return f"{scene_id}:panel_{panel_index:03d}"


def _page_id(page_number: int) -> str:
    return f"page_{page_number:03d}"


def _beat_ref(scene_id: str, beat_index: int, beat: ScreenplayBeat) -> LayoutPlanBeatRef:
    shot_hint = beat.direction if beat.direction and "shot" in beat.direction.lower() else None
    transition_significance = "high" if beat.type == "transition" else None
    emphasis_hint = "hero" if beat.type == "transition" else None
    return LayoutPlanBeatRef(
        beat_id=_beat_id(scene_id, beat_index),
        scene_id=scene_id,
        beat_index=beat_index,
        type=beat.type,
        character_id=beat.character_id,
        content=beat.content,
        direction=beat.direction,
        transition_type=beat.transition_type,
        emphasis_hint=emphasis_hint,
        shot_hint=shot_hint,
        transition_significance=transition_significance,
    )


def _dialogue_line(screenplay_beat: ScreenplayBeat) -> list[dict[str, str | None]]:
    if screenplay_beat.type != "dialogue":
        return []
    line = DialogueLine(
        character_id=screenplay_beat.character_id,
        text=screenplay_beat.content,
        type="speech",
    )
    return [line.model_dump()]


def _shot_type_for_beat(beat: ScreenplayBeat) -> str:
    if beat.type == "transition":
        return "wide"
    if beat.type == "dialogue":
        return "medium"
    content = beat.content.lower()
    if any(word in content for word in ("close", "whisper", "tear", "blink")):
        return "close-up"
    if any(word in content for word in ("crowd", "city", "landscape", "room")):
        return "wide"
    return "medium"


def _camera_angle_for_beat(beat: ScreenplayBeat) -> str:
    direction = (beat.direction or "").lower()
    if "low" in direction:
        return "low-angle"
    if "high" in direction or "overhead" in direction:
        return "high-angle"
    if "dutch" in direction:
        return "dutch-angle"
    return "eye-level"


def _shape_intent_for_beat(beat: ScreenplayBeat) -> str:
    if beat.type == "transition":
        return "wide"
    content = beat.content.lower()
    if any(word in content for word in ("tower", "stairs", "fall", "drop")):
        return "tall"
    if any(word in content for word in ("horizon", "street", "field", "landscape")):
        return "wide"
    return "rect"


def _importance_for_beat(beat: ScreenplayBeat) -> str:
    if beat.type == "transition":
        return "hero"
    if beat.type == "sfx":
        return "accent"
    return "standard"


def _generation_mode_for_shape(shape_intent: str, importance: str) -> str:
    if shape_intent in {"irregular", "bleed", "panorama"} or importance in {"hero", "splash"}:
        return "exact"
    return "master"


def _panel_from_beat(
    scene_id: str,
    beat_index: int,
    beat: ScreenplayBeat,
    scene_location_name: str,
) -> PlannedPanel:
    shape_intent = _shape_intent_for_beat(beat)
    importance = _importance_for_beat(beat)
    shot_type = _shot_type_for_beat(beat)
    camera_angle = _camera_angle_for_beat(beat)
    characters_present = [beat.character_id] if beat.character_id else []
    character_actions = {beat.character_id: beat.content} if beat.character_id and beat.type == "action" else {}
    character_expressions = {}
    if beat.character_id and beat.type == "dialogue":
        character_expressions[beat.character_id] = "speaking"
    character_positions = {beat.character_id: "center"} if beat.character_id else {}
    dialogue_load = 1 if beat.type == "dialogue" else 0
    caption_load = 1 if beat.type == "action" and not beat.character_id else 0
    aspect_preference = 1.8 if shape_intent == "wide" else 0.75 if shape_intent == "tall" else 1.0
    aspect_range = [1.4, 2.2] if shape_intent == "wide" else [0.55, 0.9] if shape_intent == "tall" else [0.8, 1.25]
    return PlannedPanel(
        panel_id=_panel_id(scene_id, beat_index),
        scene_id=scene_id,
        panel_number=beat_index,
        beat_ids=[_beat_id(scene_id, beat_index)],
        importance=importance,
        shape_intent=shape_intent,
        aspect_preference=aspect_preference,
        aspect_range=aspect_range,
        crop_policy="flexible" if shape_intent == "rect" else "preserve_subject",
        dialogue_load=dialogue_load,
        caption_load=caption_load,
        transition_in=beat.transition_type if beat.type == "transition" else None,
        transition_out=beat.transition_type if beat.type == "transition" else None,
        generation_mode=_generation_mode_for_shape(shape_intent, importance),
        shot_type=shot_type,
        camera_angle=camera_angle,
        characters_present=characters_present,
        character_actions=character_actions,
        character_expressions=character_expressions,
        character_positions=character_positions,
        background_description=scene_location_name,
        lighting=beat.direction or "",
        mood="tense" if beat.type == "transition" else "neutral",
        dialogue=_dialogue_line(beat),
        sfx=beat.content if beat.type == "sfx" else None,
    )


def _regions_for_count(count: int) -> list[list[float]]:
    templates: dict[int, list[list[float]]] = {
        1: [[0.0, 0.0, 1.0, 1.0]],
        2: [[0.0, 0.0, 1.0, 0.5], [0.0, 0.5, 1.0, 0.5]],
        3: [[0.0, 0.0, 1.0, 0.45], [0.0, 0.45, 0.5, 0.55], [0.5, 0.45, 0.5, 0.55]],
        4: [[0.0, 0.0, 0.5, 0.5], [0.5, 0.0, 0.5, 0.5], [0.0, 0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]],
        5: [[0.0, 0.0, 1.0, 0.34], [0.0, 0.34, 0.5, 0.33], [0.5, 0.34, 0.5, 0.33], [0.0, 0.67, 0.5, 0.33], [0.5, 0.67, 0.5, 0.33]],
        6: [[0.0, 0.0, 0.5, 0.33], [0.5, 0.0, 0.5, 0.33], [0.0, 0.33, 0.5, 0.34], [0.5, 0.33, 0.5, 0.34], [0.0, 0.67, 0.5, 0.33], [0.5, 0.67, 0.5, 0.33]],
    }
    return templates.get(count, templates[6])


def _paginate_scene(
    scene_id: str,
    panels: list[PlannedPanel],
    start_page_number: int,
    max_per_page: int,
) -> list[PlannedPage]:
    pages: list[PlannedPage] = []
    page_number = start_page_number
    for chunk_start in range(0, len(panels), max_per_page):
        chunk = panels[chunk_start:chunk_start + max_per_page]
        regions = _regions_for_count(len(chunk))
        pages.append(
            PlannedPage(
                page_id=_page_id(page_number),
                page_number=page_number,
                panel_ids=[panel.panel_id for panel in chunk],
                panel_geometries=[
                    PanelGeometry(
                        panel_id=panel.panel_id,
                        shape_intent=panel.shape_intent,
                        region=regions[idx],
                        aspect_ratio=(regions[idx][2] / regions[idx][3]) if regions[idx][3] else None,
                        bleed=panel.shape_intent in {"bleed", "panorama"},
                        z_index=idx,
                    )
                    for idx, panel in enumerate(chunk)
                ],
                scene_ids=[scene_id],
                scene_boundary_mode="scene_contained",
                page_rhythm_role="intro" if chunk_start == 0 else "regular",
            )
        )
        page_number += 1
    return pages


def _build_layout_plan(config: Config, project_dir: Path, story_bible: StoryBible, scene_ids: list[str]) -> LayoutPlan:
    screenplays = [_load_screenplay(project_dir, scene_id) for scene_id in scene_ids]
    location_name_by_id = {location.id: location.name for location in story_bible.locations}

    beats: list[LayoutPlanBeatRef] = []
    planned_panels: list[PlannedPanel] = []
    planned_pages: list[PlannedPage] = []
    warnings: list[str] = []
    next_page_number = 1

    for screenplay in screenplays:
        scene_location_name = location_name_by_id.get(screenplay.location_id, screenplay.location_id)
        scene_panels = [
            _panel_from_beat(screenplay.scene_id, beat_index, beat, scene_location_name)
            for beat_index, beat in enumerate(screenplay.beats, start=1)
        ]
        if not scene_panels:
            warnings.append(f"{screenplay.scene_id}: screenplay has no beats to plan")
            continue
        scene_beats = [
            _beat_ref(screenplay.scene_id, beat_index, beat)
            for beat_index, beat in enumerate(screenplay.beats, start=1)
        ]
        beats.extend(scene_beats)
        planned_panels.extend(scene_panels)
        pages = _paginate_scene(
            screenplay.scene_id,
            scene_panels,
            start_page_number=next_page_number,
            max_per_page=max(1, config.max_panels_per_page),
        )
        planned_pages.extend(pages)
        next_page_number += len(pages)

    return LayoutPlan(
        metadata=LayoutPlanMetadata(
            source_screenplay_hash=_screenplay_hash(screenplays),
            source_scene_ids=scene_ids,
            max_panels_per_page=config.max_panels_per_page,
        ),
        beats=beats,
        planned_panels=planned_panels,
        planned_pages=planned_pages,
        warnings=warnings,
    )


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    scene_ids: list[str] | None = None,
    on_event: EventCallback | None = None,
) -> None:
    """Execute layout planning from screenplay artifacts."""
    emit = on_event or _NOOP
    story_bible = _load_story_bible(project_dir)
    ids = scene_ids or [scene.id for scene in story_bible.scenes]
    layout_plan_dir = project_dir / "layout_plan"
    layout_plan_path = layout_plan_dir / "layout_plan.json"

    begin_stage(state, "layout-plan", total=len(ids))
    emit({"type": "stage_begin", "stage": "layout-plan", "total": len(ids)})
    save_state(state, project_dir)

    try:
        with make_progress(on_event) as progress:
            task = progress.add_task("Layout planning", total=len(ids))
            plan = _build_layout_plan(config, project_dir, story_bible, ids)
            layout_plan_dir.mkdir(parents=True, exist_ok=True)
            layout_plan_path.write_text(plan.model_dump_json(indent=2))
            for scene_id in ids:
                record_item_done(state, "layout-plan")
                emit(
                    {
                        "type": "stage_progress",
                        "stage": "layout-plan",
                        "done": state.stages["layout-plan"].items_done,
                        "total": state.stages["layout-plan"].items_total,
                    }
                )
                progress.advance(task)

        complete_stage(state, "layout-plan")
        emit(
            {
                "type": "stage_complete",
                "stage": "layout-plan",
                "done": state.stages["layout-plan"].items_done,
                "total": state.stages["layout-plan"].items_total,
            }
        )
        save_state(state, project_dir)
        console.print(
            f"[green]Stage 4 complete.[/green] Wrote "
            f"{layout_plan_path.relative_to(project_dir)} "
            f"with {len(plan.planned_panels)} planned panels across {len(plan.planned_pages)} pages."
        )
        emit(
            {
                "type": "log",
                "stage": "layout-plan",
                "level": "info",
                "message": (
                    f"Wrote {layout_plan_path.relative_to(project_dir)} "
                    f"with {len(plan.planned_panels)} planned panels across {len(plan.planned_pages)} pages."
                ),
            }
        )

    except Exception as exc:
        fail_stage(state, "layout-plan", str(exc))
        emit({"type": "stage_fail", "stage": "layout-plan", "message": str(exc)})
        save_state(state, project_dir)
        raise
