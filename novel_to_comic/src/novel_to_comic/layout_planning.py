"""Helpers for reading, mutating, and projecting layout plans."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict, cast

from novel_to_comic import artifacts
from novel_to_comic.assembly.html_renderer import PAGE_H, PAGE_W
from novel_to_comic.models.comic_page import (
    Bubble,
    ComicPage,
    PagePanel,
    Sfx,
    infer_sfx_intensity,
    infer_sfx_kind,
    normalize_sfx_text,
)
from novel_to_comic.models.layout_plan import GenerationMode, LayoutPlan, NarrationDecision, PanelGeometry, PanelImportance, PlannedPage, PlannedPanel, ShapeIntent
from novel_to_comic.models.panel import DialogueLine, PanelBreakdown
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.panel_aspect import dimensions_for_generation_aspect, generation_shape_for_aspect

CONTENT_MARGIN = 30.0
CONTENT_FOOTER = 48.0

LAYOUT_PRESET_GEOMETRIES: dict[str, list[tuple[list[float], list[list[float]] | None]]] = {
    # ── 1-panel ──────────────────────────────────────────────────────────────
    "single": [
        ([0.0, 0.0, 1.0, 1.0], None),
    ],
    # ── 2-panel ──────────────────────────────────────────────────────────────
    "stacked_2": [
        ([0.0, 0.0, 1.0, 0.5], None),
        ([0.0, 0.5, 1.0, 0.5], None),
    ],
    "side_2": [
        ([0.0, 0.0, 0.5, 1.0], None),
        ([0.5, 0.0, 0.5, 1.0], None),
    ],
    # Large hero top (60%) + smaller follow panel (40%)
    "hero_top_2": [
        ([0.0, 0.0, 1.0, 0.60], None),
        ([0.0, 0.60, 1.0, 0.40], None),
    ],
    # ── 3-panel ──────────────────────────────────────────────────────────────
    # Wide hero top + 2 equal below
    "hero_top_3": [
        ([0.0, 0.0, 1.0, 0.45], None),
        ([0.0, 0.45, 0.5, 0.55], None),
        ([0.5, 0.45, 0.5, 0.55], None),
    ],
    # Large left column + 2 stacked on right
    "hero_left_3": [
        ([0.0, 0.0, 0.60, 1.0], None),
        ([0.60, 0.0, 0.40, 0.5], None),
        ([0.60, 0.5, 0.40, 0.5], None),
    ],
    "vertical_trio": [
        ([0.0, 0.0, 1 / 3, 1.0], None),
        ([1 / 3, 0.0, 1 / 3, 1.0], None),
        ([2 / 3, 0.0, 1 / 3, 1.0], None),
    ],
    # ── 4-panel ──────────────────────────────────────────────────────────────
    "2x2": [
        ([0.0, 0.0, 0.5, 0.5], None),
        ([0.5, 0.0, 0.5, 0.5], None),
        ([0.0, 0.5, 0.5, 0.5], None),
        ([0.5, 0.5, 0.5, 0.5], None),
    ],
    # Full-width hero top + 3 equal below
    "hero_top_4": [
        ([0.0, 0.0, 1.0, 0.42], None),
        ([0.0, 0.42, 1 / 3, 0.58], None),
        ([1 / 3, 0.42, 1 / 3, 0.58], None),
        ([2 / 3, 0.42, 1 / 3, 0.58], None),
    ],
    # ── 5-panel ──────────────────────────────────────────────────────────────
    "splash+4": [
        ([0.0, 0.0, 1.0, 0.45], None),
        ([0.0, 0.45, 0.5, 0.275], None),
        ([0.5, 0.45, 0.5, 0.275], None),
        ([0.0, 0.725, 0.5, 0.275], None),
        ([0.5, 0.725, 0.5, 0.275], None),
    ],
    "wide_opening": [
        ([0.0, 0.0, 1.0, 0.32], None),
        ([0.0, 0.32, 0.5, 0.34], None),
        ([0.5, 0.32, 0.5, 0.34], None),
        ([0.0, 0.66, 0.5, 0.34], None),
        ([0.5, 0.66, 0.5, 0.34], None),
    ],
    # ── 6-panel ──────────────────────────────────────────────────────────────
    "2x3": [
        ([0.0, 0.0, 1 / 3, 0.5], None),
        ([1 / 3, 0.0, 1 / 3, 0.5], None),
        ([2 / 3, 0.0, 1 / 3, 0.5], None),
        ([0.0, 0.5, 1 / 3, 0.5], None),
        ([1 / 3, 0.5, 1 / 3, 0.5], None),
        ([2 / 3, 0.5, 1 / 3, 0.5], None),
    ],
    "3x2": [
        ([0.0, 0.0, 0.5, 1 / 3], None),
        ([0.5, 0.0, 0.5, 1 / 3], None),
        ([0.0, 1 / 3, 0.5, 1 / 3], None),
        ([0.5, 1 / 3, 0.5, 1 / 3], None),
        ([0.0, 2 / 3, 0.5, 1 / 3], None),
        ([0.5, 2 / 3, 0.5, 1 / 3], None),
    ],
}

# Maps (panel_count, has_hero) to the best preset name.
_TEMPLATE_SELECTION: dict[tuple[int, bool], str] = {
    (1, False): "single",
    (1, True):  "single",
    (2, False): "stacked_2",
    (2, True):  "hero_top_2",
    (3, False): "vertical_trio",
    (3, True):  "hero_top_3",
    (4, False): "2x2",
    (4, True):  "hero_top_4",
    (5, False): "wide_opening",
    (5, True):  "splash+4",
    (6, False): "2x3",
    (6, True):  "3x2",
}


def select_layout_template(panels: "list") -> str:  # list[PlannedPanel]
    """Return the best LAYOUT_PRESET_GEOMETRIES key for a list of PlannedPanels."""
    count = min(len(panels), 6)
    if count == 0:
        return "single"
    has_hero = any(getattr(p, "importance", "standard") in {"hero", "splash"} for p in panels)
    return _TEMPLATE_SELECTION.get((count, has_hero), "2x3")


def load_layout_plan(project_dir: Path) -> LayoutPlan:
    plan = artifacts.read_layout_plan(project_dir)
    apply_generation_aspects(plan)
    return plan


def save_layout_plan(project_dir: Path, plan: LayoutPlan) -> None:
    artifacts.write_layout_plan(project_dir, plan)


def planned_panel_index(plan: LayoutPlan) -> dict[str, PlannedPanel]:
    return {panel.panel_id: panel for panel in plan.planned_panels}


def apply_generation_aspects(plan: LayoutPlan) -> None:
    """Hydrate planned panels with canonical generation aspect from page slots."""
    panels = planned_panel_index(plan)
    for page in plan.planned_pages:
        for geometry in page.panel_geometries:
            panel = panels.get(geometry.panel_id)
            if panel is None:
                continue
            aspect_ratio = geometry.aspect_ratio
            if aspect_ratio is None and len(geometry.region) >= 4 and geometry.region[3]:
                aspect_ratio = geometry.region[2] / geometry.region[3]
            shape = generation_shape_for_aspect(aspect_ratio)
            width, height = dimensions_for_generation_aspect(aspect_ratio)
            panel.generation_aspect_ratio = aspect_ratio
            panel.generation_width = width
            panel.generation_height = height
            panel.generation_shape = shape
            panel.generation_aspect_source = "page_geometry"


def scene_panel_map(plan: LayoutPlan) -> dict[str, list[PlannedPanel]]:
    scenes: dict[str, list[PlannedPanel]] = {}
    for panel in plan.planned_panels:
        scenes.setdefault(panel.scene_id, []).append(panel)
    for panels in scenes.values():
        panels.sort(key=lambda panel: panel.panel_number)
    return scenes


def _page_lookup(plan: LayoutPlan) -> dict[str, PlannedPage]:
    return {page.page_id: page for page in plan.planned_pages}


def planned_panel_to_breakdown(panel: PlannedPanel) -> PanelBreakdown:
    return PanelBreakdown(
        scene_id=panel.scene_id,
        panel_number=panel.panel_number,
        shot_type=panel.shot_type,
        camera_angle=panel.camera_angle,
        characters_present=panel.characters_present,
        character_actions=panel.character_actions,
        character_expressions=panel.character_expressions,
        character_positions=panel.character_positions,
        background_description=_append_visual_requirements(
            panel.background_description,
            panel.key_objects,
            panel.visual_requirements,
        ),
        lighting=panel.lighting,
        mood=panel.mood,
        dialogue=[DialogueLine.model_validate(line) for line in panel.dialogue],
        sfx=[s.text for s in panel.sfx],
        transition_type=panel.transition_out,
        transition_note=None,
    )


def _append_visual_requirements(
    background: str,
    key_objects: list[str],
    visual_requirements: list[str],
) -> str:
    parts = [background.strip()] if background and background.strip() else []
    if key_objects:
        parts.append("Key objects: " + "; ".join(key_objects))
    if visual_requirements:
        parts.append("Must show: " + "; ".join(visual_requirements))
    return " ".join(parts)


def _caption_text(decision: NarrationDecision) -> str:
    return decision.caption_text_override or decision.caption_text or decision.source_text


def _remove_narration_from_panel(panel: PlannedPanel, beat_id: str) -> PlannedPanel:
    dialogue = [
        line for line in panel.dialogue
        if line.get("source_beat_id") != beat_id
    ]
    has_narration = any(line.get("type") == "narration" for line in dialogue)
    return panel.model_copy(
        update={
            "dialogue": dialogue,
            "caption_load": sum(1 for line in dialogue if line.get("type") == "narration"),
            "has_narration_caption": has_narration,
            "narration_mode": panel.narration_mode if has_narration else None,
            "preferred_caption_zone": panel.preferred_caption_zone if has_narration else None,
        }
    )


def _apply_narration_to_panel(panel: PlannedPanel, decision: NarrationDecision) -> PlannedPanel:
    dialogue = [
        line for line in panel.dialogue
        if line.get("source_beat_id") != decision.beat_id
    ]
    if decision.decision == "rendered":
        dialogue.append(
            DialogueLine(
                character_id=None,
                text=_caption_text(decision),
                type="narration",
                source_beat_id=decision.beat_id,
                source_text=decision.source_text,
                narration_mode=decision.mode,
                preferred_zone=decision.preferred_zone,
            ).model_dump()
        )
    beat_ids = list(panel.beat_ids)
    if decision.decision == "rendered" and decision.beat_id not in beat_ids:
        beat_ids.append(decision.beat_id)
    has_narration = any(line.get("type") == "narration" for line in dialogue)
    return panel.model_copy(
        update={
            "beat_ids": beat_ids,
            "dialogue": dialogue,
            "caption_load": sum(1 for line in dialogue if line.get("type") == "narration"),
            "has_narration_caption": has_narration,
            "narration_mode": decision.mode if decision.decision == "rendered" else None,
            "preferred_caption_zone": decision.preferred_zone if decision.decision == "rendered" else None,
        }
    )


def sync_narration_decisions(plan: LayoutPlan) -> LayoutPlan:
    panels = planned_panel_index(plan)
    for decision in plan.narration_decisions:
        for panel_id, panel in list(panels.items()):
            panels[panel_id] = _remove_narration_from_panel(panel, decision.beat_id)
        if decision.decision == "rendered" and decision.panel_id in panels:
            panels[decision.panel_id] = _apply_narration_to_panel(panels[decision.panel_id], decision)
    plan.planned_panels = [panels[panel.panel_id] for panel in plan.planned_panels]
    return plan


class NarrationChangeImpact(TypedDict):
    impact: str
    affected_stages: list[str]
    affected_panels: list[str]
    requires_confirmation: bool
    reason: str


def classify_narration_change_impact(
    before: NarrationDecision,
    after: NarrationDecision,
) -> NarrationChangeImpact:
    affected_panels = sorted(
        {
            panel_id
            for panel_id in (before.panel_id, after.panel_id)
            if panel_id
        }
    )
    if before.mode != "caption_panel" and after.mode == "caption_panel":
        impact = "replan_scene"
        stages = ["plan", "storyboard", "direct", "draw", "compose"]
        reason = "Changing to a caption panel can alter panel count, page layout, and generated images."
    elif before.decision != after.decision:
        impact = "plan_only" if after.decision != "rendered" or after.mode != "caption_panel" else "replan_scene"
        stages = ["storyboard", "direct", "compose"] if impact == "plan_only" else ["plan", "storyboard", "direct", "draw", "compose"]
        reason = "Changing whether narration is rendered updates panel text and downstream structured artifacts."
    elif before.panel_id != after.panel_id or before.preferred_zone != after.preferred_zone:
        impact = "plan_only"
        stages = ["storyboard", "direct", "compose"]
        reason = "Moving an attached caption updates layout/direct metadata but does not require a redraw by default."
    elif before.caption_text_override != after.caption_text_override:
        impact = "compose_only"
        stages = ["compose"]
        reason = "Caption text changes are lettered in compose and do not change panel art."
    else:
        impact = "compose_only"
        stages = ["compose"]
        reason = "No image-affecting narration fields changed."
    return {
        "impact": impact,
        "affected_stages": stages,
        "affected_panels": affected_panels,
        "requires_confirmation": impact != "compose_only",
        "reason": reason,
    }


def apply_narration_decision_patch(plan: LayoutPlan, beat_id: str, patch: dict) -> tuple[LayoutPlan, NarrationChangeImpact]:
    decisions = {decision.beat_id: decision for decision in plan.narration_decisions}
    before = decisions.get(beat_id)
    if before is None:
        raise KeyError(beat_id)
    data = before.model_dump()
    for key in (
        "decision",
        "mode",
        "panel_id",
        "preferred_zone",
        "decision_reason",
        "caption_text_override",
    ):
        if key in patch:
            data[key] = patch[key]
    if data["decision"] != "rendered":
        data["mode"] = None
        data["panel_id"] = None
    after = NarrationDecision.model_validate(data)
    impact = classify_narration_change_impact(before, after)
    plan.narration_decisions = [
        after if decision.beat_id == beat_id else decision
        for decision in plan.narration_decisions
    ]
    sync_narration_decisions(plan)
    for panel_id in impact.get("affected_panels", []):
        if isinstance(panel_id, str):
            _set_regeneration_impact(
                plan,
                panel_id,
                "required" if impact.get("impact") in {"redraw_selected_panels", "replan_scene"} else "recommended",
            )
    _record_override(plan, "narration", beat_id, patch)
    return plan, impact


def prompt_path_for_panel(project_dir: Path, panel: PlannedPanel) -> Path:
    return artifacts.panel_prompt_path(project_dir, panel.scene_id, panel.panel_number)


def image_path_for_panel(project_dir: Path, panel: PlannedPanel) -> Path:
    return artifacts.panel_image_path(project_dir, panel.scene_id, panel.panel_number)


def _content_box() -> tuple[float, float]:
    return PAGE_W - CONTENT_MARGIN * 2, PAGE_H - CONTENT_FOOTER - CONTENT_MARGIN * 2


def _region_to_pixels(region: list[float]) -> tuple[float, float, float, float]:
    content_w, content_h = _content_box()
    x, y, w, h = region
    return (
        CONTENT_MARGIN + x * content_w,
        CONTENT_MARGIN + y * content_h,
        w * content_w,
        h * content_h,
    )


def _polygon_to_clip_path(polygon: list[list[float]] | None) -> str | None:
    if not polygon:
        return None
    points = ", ".join(f"{x * 100:.2f}% {y * 100:.2f}%" for x, y in polygon)
    return f"polygon({points})"


def _default_polygon_for_shape(shape_intent: str) -> list[list[float]]:
    return []


class _PanelGeometryStyle(TypedDict):
    x: float
    y: float
    width: float
    height: float
    clip_path: str | None
    z_index: int
    shape_intent: ShapeIntent


def _panel_geometry_style(geometry: PanelGeometry, index: int) -> _PanelGeometryStyle:
    x, y, width, height = _region_to_pixels(geometry.region)
    polygon = geometry.polygon or _default_polygon_for_shape(geometry.shape_intent)
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "clip_path": _polygon_to_clip_path(polygon),
        "z_index": geometry.z_index if geometry.z_index is not None else index,
        "shape_intent": geometry.shape_intent,
    }


def _page_style_key(page: ComicPage) -> str:
    return page.source_page_id or f"page_{page.page_number:03d}"


def _panel_style_key(panel: PagePanel) -> str:
    return panel.planned_panel_id or panel.id


def project_layout_plan_to_pages(
    project_dir: Path,
    story_bible: StoryBible,
    theme_name: str,
    existing_pages: list[ComicPage] | None = None,
) -> list[ComicPage]:
    plan = load_layout_plan(project_dir)
    panel_lookup = planned_panel_index(plan)
    existing_by_page = {_page_style_key(page): page for page in existing_pages or []}
    existing_panels: dict[str, PagePanel] = {}
    for page in existing_pages or []:
        for panel in page.panels:
            existing_panels[_panel_style_key(panel)] = panel

    char_name_map = {c.id: c.name.split()[0] for c in story_bible.characters}
    pages: list[ComicPage] = []

    for planned_page in plan.planned_pages:
        previous_page = existing_by_page.get(planned_page.page_id)
        page_theme = previous_page.theme if previous_page else theme_name
        page_style_vars = previous_page.style_vars if previous_page else {}

        page_panels: list[PagePanel] = []
        for index, geometry in enumerate(planned_page.panel_geometries):
            planned_panel = panel_lookup.get(geometry.panel_id)
            if planned_panel is None:
                continue
            breakdown = planned_panel_to_breakdown(planned_panel)
            existing_panel = existing_panels.get(planned_panel.panel_id)

            bubbles: list[Bubble]
            sfx_items: list[Sfx]
            image_offset_x: float | None
            image_offset_y: float | None
            if existing_panel:
                bubbles = existing_panel.bubbles
                sfx_items = existing_panel.sfx
                image_offset_x = existing_panel.image_offset_x
                image_offset_y = existing_panel.image_offset_y
            else:
                bubbles = []
                show_labels = len(breakdown.characters_present) >= 3
                char_sides: dict[str, str] = {}
                for cid, pos in breakdown.character_positions.items():
                    p = pos.lower()
                    char_sides[cid] = "right" if "right" in p else ("center" if "center" in p else "left")
                alt = ["left", "right"]
                alt_idx = 0
                for bi, dl in enumerate(breakdown.dialogue):
                    is_narration = dl.type == "narration"
                    side = char_sides.get(dl.character_id) if dl.character_id else None
                    if side is None and not is_narration:
                        side = alt[alt_idx % 2]
                        alt_idx += 1
                    bubbles.append(
                        Bubble(
                            id=f"{breakdown.scene_id}-p{breakdown.panel_number}-b{bi}",
                            type=dl.type if dl.type in ("speech", "thought", "narration") else "speech",
                            text=dl.text,
                            speaker_id=dl.character_id or None,
                            speaker_name=char_name_map.get(dl.character_id) if dl.character_id and show_labels else None,
                            source_beat_id=dl.source_beat_id,
                            source_text=dl.source_text,
                            narration_mode=dl.narration_mode,
                            preferred_zone=dl.preferred_zone,
                            side=cast(Literal["left", "right", "center"], side or "left"),
                        )
                    )
                sfx_items = []
                for raw in breakdown.sfx:
                    text = normalize_sfx_text(raw)
                    if not text:
                        continue
                    sfx_items.append(Sfx(
                        text=text,
                        kind=infer_sfx_kind(text),
                        intensity=infer_sfx_intensity(text),
                    ))
                image_offset_x = None
                image_offset_y = None

            page_panels.append(
                PagePanel(
                    id=f"{planned_panel.scene_id}-{planned_panel.panel_number:03d}",
                    planned_panel_id=planned_panel.panel_id,
                    image_path=str(image_path_for_panel(project_dir, planned_panel).relative_to(project_dir)),
                    scene_id=planned_panel.scene_id,
                    panel_number=planned_panel.panel_number,
                    importance=planned_panel.importance,
                    generation_mode=planned_panel.generation_mode,
                    bubbles=bubbles,
                    sfx=sfx_items,
                    image_offset_x=image_offset_x,
                    image_offset_y=image_offset_y,
                    **_panel_geometry_style(geometry, index),
                )
            )

        pages.append(
            ComicPage(
                page_number=planned_page.page_number,
                source_page_id=planned_page.page_id,
                theme=page_theme,
                layout=str(len(page_panels)) if len(page_panels) <= 6 else "many",
                layout_mode="freeform",
                style_vars=page_style_vars,
                panels=page_panels,
            )
        )

    return pages


def write_projected_pages(project_dir: Path, pages: list[ComicPage]) -> list[Path]:
    pages_dir = artifacts.compose_pages_dir(project_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob("page_*.json"):
        old.unlink()
    written: list[Path] = []
    for page in pages:
        artifacts.write_compose_page(project_dir, page.page_number, page)
        written.append(artifacts.compose_page_path(project_dir, page.page_number))
    return written


def _record_override(plan: LayoutPlan, kind: str, key: str, payload: dict) -> None:
    bucket = plan.user_overrides.setdefault(kind, {})
    if isinstance(bucket, dict):
        bucket[key] = payload


def _set_regeneration_impact(plan: LayoutPlan, panel_id: str, impact: str) -> None:
    current = plan.regeneration_impact.get(panel_id)
    if current == "required":
        return
    plan.regeneration_impact[panel_id] = impact


def apply_panel_override(
    plan: LayoutPlan,
    panel_id: str,
    *,
    importance: PanelImportance | None = None,
    shape_intent: ShapeIntent | None = None,
    generation_mode: GenerationMode | None = None,
) -> LayoutPlan:
    panel = planned_panel_index(plan).get(panel_id)
    if panel is None:
        raise KeyError(panel_id)
    payload: dict[str, object] = {}
    impact = "recommended"
    if importance is not None:
        panel.importance = importance
        payload["importance"] = importance
    if shape_intent is not None:
        panel.shape_intent = shape_intent
        payload["shape_intent"] = shape_intent
        panel.regeneration_status = "recommended"
        panel.image_fit_status = "cropped_risk"
        for page in plan.planned_pages:
            for geometry in page.panel_geometries:
                if geometry.panel_id == panel_id:
                    geometry.shape_intent = shape_intent
                    if shape_intent == "irregular" and not geometry.polygon:
                        geometry.polygon = _default_polygon_for_shape(shape_intent)
                    elif shape_intent != "irregular" and geometry.polygon:
                        geometry.polygon = []
    if generation_mode is not None:
        panel.generation_mode = generation_mode
        payload["generation_mode"] = generation_mode
        panel.regeneration_status = "required" if generation_mode == "exact" else "recommended"
        panel.image_fit_status = "needs_redraw" if generation_mode == "exact" else "cropped_risk"
        impact = "required" if generation_mode == "exact" else impact
    if payload:
        _record_override(plan, "panels", panel_id, payload)
        _set_regeneration_impact(plan, panel_id, impact)
    return plan


def _repaginate_scene_panels(scene_panels: list[PlannedPanel], max_per_page: int) -> list[list[PlannedPanel]]:
    return [
        scene_panels[index:index + max_per_page]
        for index in range(0, len(scene_panels), max_per_page)
    ]


def repaginate_layout_plan(plan: LayoutPlan, *, panels_per_page: int) -> LayoutPlan:
    scene_panels = scene_panel_map(plan)
    new_pages: list[PlannedPage] = []
    page_number = 1
    for scene_id in sorted(scene_panels.keys()):
        for chunk in _repaginate_scene_panels(scene_panels[scene_id], panels_per_page):
            geometries = []
            preset = LAYOUT_PRESET_GEOMETRIES.get(f"{min(len(chunk), 3)}x2")
            if preset is None:
                preset = LAYOUT_PRESET_GEOMETRIES["2x2"]
            for idx, panel in enumerate(chunk):
                region, polygon = preset[idx] if idx < len(preset) else ([0.0, 0.0, 1.0, 1.0], None)
                geometries.append(
                    PanelGeometry(
                        panel_id=panel.panel_id,
                        shape_intent=panel.shape_intent,
                        region=region,
                        polygon=polygon or [],
                        aspect_ratio=(region[2] / region[3]) if region[3] else None,
                        bleed=panel.shape_intent == "bleed",
                        z_index=idx,
                    )
                )
            new_pages.append(
                PlannedPage(
                    page_id=f"page_{page_number:03d}",
                    page_number=page_number,
                    panel_ids=[panel.panel_id for panel in chunk],
                    panel_geometries=geometries,
                    scene_ids=[scene_id],
                    scene_boundary_mode="scene_contained",
                    page_rhythm_role="intro" if page_number == 1 else "regular",
                )
            )
            page_number += 1
    plan.planned_pages = new_pages
    plan.metadata.max_panels_per_page = panels_per_page
    for panel in plan.planned_panels:
        panel.regeneration_status = "recommended"
        panel.image_fit_status = "cropped_risk"
        _set_regeneration_impact(plan, panel.panel_id, "recommended")
    _record_override(plan, "project", "repagination", {"panels_per_page": panels_per_page})
    return plan


def apply_page_layout_preset(plan: LayoutPlan, page_number: int, preset_name: str) -> LayoutPlan:
    if preset_name not in LAYOUT_PRESET_GEOMETRIES:
        raise KeyError(preset_name)
    page = next((page for page in plan.planned_pages if page.page_number == page_number), None)
    if page is None:
        raise KeyError(f"page_{page_number:03d}")
    preset = LAYOUT_PRESET_GEOMETRIES[preset_name]
    new_geometries: list[PanelGeometry] = []
    for idx, panel_id in enumerate(page.panel_ids):
        region, polygon = preset[min(idx, len(preset) - 1)]
        panel = planned_panel_index(plan)[panel_id]
        shape_intent = "irregular" if polygon else panel.shape_intent
        panel.regeneration_status = "recommended"
        panel.image_fit_status = "cropped_risk"
        _set_regeneration_impact(plan, panel_id, "recommended")
        new_geometries.append(
            PanelGeometry(
                panel_id=panel_id,
                shape_intent=shape_intent,
                region=region,
                polygon=polygon or [],
                aspect_ratio=(region[2] / region[3]) if region[3] else None,
                bleed=shape_intent == "bleed",
                z_index=idx,
            )
        )
    page.panel_geometries = new_geometries
    page.page_rhythm_role = "climax" if preset_name in {"splash+4", "wide_opening"} else page.page_rhythm_role
    _record_override(plan, "pages", page.page_id, {"layout_preset": preset_name})
    return plan


def reorder_planned_pages(plan: LayoutPlan, pages_spec: list[dict]) -> LayoutPlan:
    by_number = {page.page_number: page for page in plan.planned_pages}
    panel_lookup = planned_panel_index(plan)
    for page_spec in pages_spec:
        page_number = int(page_spec["page_number"])
        page = by_number.get(page_number)
        if page is None:
            continue
        page.panel_ids = list(page_spec.get("panel_ids", []))
        existing_geometries = list(page.panel_geometries)
        remapped_geometries: list[PanelGeometry] = []
        for idx, panel_id in enumerate(page.panel_ids):
            geometry = next((geom for geom in existing_geometries if geom.panel_id == panel_id), None)
            if geometry is None:
                template = (
                    existing_geometries[min(idx, len(existing_geometries) - 1)]
                    if existing_geometries
                    else PanelGeometry(panel_id=panel_id)
                )
                planned_panel = panel_lookup.get(panel_id)
                geometry = PanelGeometry(
                    panel_id=panel_id,
                    shape_intent=planned_panel.shape_intent if planned_panel else template.shape_intent,
                    region=list(template.region),
                    polygon=[list(point) for point in template.polygon],
                    aspect_ratio=template.aspect_ratio,
                    bleed=template.bleed,
                    z_index=idx,
                )
            else:
                geometry.panel_id = panel_id
                geometry.z_index = idx
            remapped_geometries.append(geometry)
        page.panel_geometries = remapped_geometries
        for panel_id in page.panel_ids:
            _set_regeneration_impact(plan, panel_id, "recommended")
        _record_override(plan, "pages", page.page_id, {"panel_ids": page.panel_ids})
    return plan


def structural_summary(plan: LayoutPlan) -> dict[str, object]:
    return {
        "planned_panels": len(plan.planned_panels),
        "planned_pages": len(plan.planned_pages),
        "warnings": plan.warnings,
        "user_overrides": plan.user_overrides,
    }


def persist_projected_pages(
    project_dir: Path,
    story_bible: StoryBible,
    theme_name: str,
) -> list[ComicPage]:
    existing = []
    try:
        existing = artifacts.list_compose_pages(project_dir)
    except Exception:
        pass
    pages = project_layout_plan_to_pages(project_dir, story_bible, theme_name, existing_pages=existing)
    write_projected_pages(project_dir, pages)
    return pages


def dump_structural_response(plan: LayoutPlan, pages: list[ComicPage]) -> dict[str, object]:
    return {
        "plan": plan.model_dump(),
        "pages": [page.model_dump() for page in pages],
        "summary": structural_summary(plan),
    }
