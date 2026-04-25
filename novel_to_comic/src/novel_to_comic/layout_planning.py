"""Helpers for reading, mutating, and projecting layout plans."""

from __future__ import annotations

import json
from pathlib import Path

from novel_to_comic.assembly.html_renderer import PAGE_H, PAGE_W
from novel_to_comic.models.comic_page import Bubble, ComicPage, PagePanel, Sfx
from novel_to_comic.models.layout_plan import LayoutPlan, PanelGeometry, PlannedPage, PlannedPanel
from novel_to_comic.models.panel import DialogueLine, PanelBreakdown
from novel_to_comic.models.story_bible import StoryBible

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
        ([0.0, 0.0, 1.0, 0.60], [[0.0, 0.0], [1.0, 0.02], [1.0, 1.0], [0.0, 0.96]]),
        ([0.0, 0.60, 1.0, 0.40], None),
    ],
    # ── 3-panel ──────────────────────────────────────────────────────────────
    # Wide hero top + 2 equal below
    "hero_top_3": [
        ([0.0, 0.0, 1.0, 0.45], [[0.0, 0.02], [1.0, 0.0], [1.0, 1.0], [0.02, 0.96]]),
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
        ([0.0, 0.0, 1.0, 0.42], [[0.02, 0.0], [1.0, 0.03], [0.98, 1.0], [0.0, 0.97]]),
        ([0.0, 0.42, 1 / 3, 0.58], None),
        ([1 / 3, 0.42, 1 / 3, 0.58], None),
        ([2 / 3, 0.42, 1 / 3, 0.58], None),
    ],
    # ── 5-panel ──────────────────────────────────────────────────────────────
    "splash+4": [
        ([0.0, 0.0, 1.0, 0.45], [[0.0, 0.02], [1.0, 0.0], [1.0, 1.0], [0.02, 0.94]]),
        ([0.0, 0.45, 0.5, 0.275], None),
        ([0.5, 0.45, 0.5, 0.275], None),
        ([0.0, 0.725, 0.5, 0.275], None),
        ([0.5, 0.725, 0.5, 0.275], None),
    ],
    "wide_opening": [
        ([0.0, 0.0, 1.0, 0.32], [[0.02, 0.0], [1.0, 0.04], [0.98, 1.0], [0.0, 0.96]]),
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


def _layout_plan_path(project_dir: Path) -> Path:
    return project_dir / "plan" / "layout_plan.json"


def load_layout_plan(project_dir: Path) -> LayoutPlan:
    path = _layout_plan_path(project_dir)
    return LayoutPlan.model_validate_json(path.read_text())


def save_layout_plan(project_dir: Path, plan: LayoutPlan) -> None:
    path = _layout_plan_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2))


def planned_panel_index(plan: LayoutPlan) -> dict[str, PlannedPanel]:
    return {panel.panel_id: panel for panel in plan.planned_panels}


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
        background_description=panel.background_description,
        lighting=panel.lighting,
        mood=panel.mood,
        dialogue=[DialogueLine.model_validate(line) for line in panel.dialogue],
        sfx=panel.sfx,
        transition_type=panel.transition_out,
        transition_note=None,
    )


def prompt_path_for_panel(project_dir: Path, panel: PlannedPanel) -> Path:
    return project_dir / "direct" / panel.scene_id / f"panel_{panel.panel_number:03d}.json"


def image_path_for_panel(project_dir: Path, panel: PlannedPanel) -> Path:
    return project_dir / "draw" / panel.scene_id / f"panel_{panel.panel_number:03d}.png"


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
    if shape_intent == "irregular":
        return [[0.03, 0.0], [1.0, 0.04], [0.95, 1.0], [0.0, 0.95]]
    if shape_intent == "wide":
        return [[0.0, 0.03], [1.0, 0.0], [0.98, 1.0], [0.02, 0.97]]
    if shape_intent == "bleed":
        return [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    return []


def _panel_geometry_style(geometry: PanelGeometry, index: int) -> dict[str, object]:
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
            sfx: Sfx | None
            image_offset_x: float | None
            image_offset_y: float | None
            if existing_panel:
                bubbles = existing_panel.bubbles
                sfx = existing_panel.sfx
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
                    side = char_sides.get(dl.character_id)
                    if side is None and not is_narration:
                        side = alt[alt_idx % 2]
                        alt_idx += 1
                    bubbles.append(
                        Bubble(
                            id=f"{breakdown.scene_id}-p{breakdown.panel_number}-b{bi}",
                            type=dl.type if dl.type in ("speech", "thought", "narration") else "speech",
                            text=dl.text,
                            speaker_id=dl.character_id or None,
                            speaker_name=char_name_map.get(dl.character_id) if show_labels else None,
                            side=side or "left",
                        )
                    )
                sfx = Sfx(text=breakdown.sfx) if breakdown.sfx else None
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
                    sfx=sfx,
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
    pages_dir = project_dir / "compose" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob("page_*.json"):
        old.unlink()
    written: list[Path] = []
    for page in pages:
        path = pages_dir / f"page_{page.page_number:03d}.json"
        path.write_text(page.model_dump_json(indent=2))
        written.append(path)
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
    importance: str | None = None,
    shape_intent: str | None = None,
    generation_mode: str | None = None,
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
    pages_dir = project_dir / "compose" / "pages"
    existing = []
    if pages_dir.exists():
        for path in sorted(pages_dir.glob("page_*.json")):
            try:
                existing.append(ComicPage.model_validate_json(path.read_text()))
            except Exception:
                continue
    pages = project_layout_plan_to_pages(project_dir, story_bible, theme_name, existing_pages=existing)
    write_projected_pages(project_dir, pages)
    return pages


def dump_structural_response(plan: LayoutPlan, pages: list[ComicPage]) -> dict[str, object]:
    return {
        "plan": plan.model_dump(),
        "pages": [page.model_dump() for page in pages],
        "summary": structural_summary(plan),
    }
