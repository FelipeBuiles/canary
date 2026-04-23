"""Pydantic models for the layout planning artifact."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PanelImportance = Literal["standard", "accent", "hero", "splash", "inset"]
ShapeIntent = Literal["rect", "tall", "wide", "panorama", "bleed", "irregular"]
GenerationMode = Literal["master", "exact"]
ImageFitStatus = Literal["unknown", "compatible", "cropped_risk", "needs_redraw"]
RegenerationStatus = Literal["not_needed", "recommended", "required"]
SceneBoundaryMode = Literal["scene_contained", "cross_scene_exception"]
PageRhythmRole = Literal["regular", "intro", "climax", "transition"]


class LayoutPlanBeatRef(BaseModel):
    beat_id: str
    scene_id: str
    beat_index: int
    type: str
    character_id: str | None = None
    content: str
    direction: str | None = None
    transition_type: str | None = None
    emphasis_hint: str | None = None
    shot_hint: str | None = None
    transition_significance: str | None = None


class PanelGeometry(BaseModel):
    panel_id: str
    shape_intent: ShapeIntent = "rect"
    region: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    polygon: list[list[float]] = Field(default_factory=list)
    aspect_ratio: float | None = None
    bleed: bool = False
    z_index: int = 0


class PlannedPanel(BaseModel):
    panel_id: str
    scene_id: str
    panel_number: int
    beat_ids: list[str] = Field(default_factory=list)
    importance: PanelImportance = "standard"
    shape_intent: ShapeIntent = "rect"
    aspect_preference: float | None = None
    aspect_range: list[float] = Field(default_factory=list)
    crop_policy: str = "flexible"
    dialogue_load: int = 0
    caption_load: int = 0
    transition_in: str | None = None
    transition_out: str | None = None
    generation_mode: GenerationMode = "master"
    image_fit_status: ImageFitStatus = "unknown"
    regeneration_status: RegenerationStatus = "not_needed"
    shot_type: str = "medium"
    camera_angle: str = "eye-level"
    characters_present: list[str] = Field(default_factory=list)
    character_actions: dict[str, str] = Field(default_factory=dict)
    character_expressions: dict[str, str] = Field(default_factory=dict)
    character_positions: dict[str, str] = Field(default_factory=dict)
    background_description: str = ""
    lighting: str = ""
    mood: str = ""
    dialogue: list[dict[str, str | None]] = Field(default_factory=list)
    sfx: str | None = None


class PlannedPage(BaseModel):
    page_id: str
    page_number: int
    panel_ids: list[str] = Field(default_factory=list)
    panel_geometries: list[PanelGeometry] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    scene_boundary_mode: SceneBoundaryMode = "scene_contained"
    page_rhythm_role: PageRhythmRole = "regular"
    spread_id: str | None = None
    cross_scene_reason: str | None = None


class LayoutPlanMetadata(BaseModel):
    planner_version: int = 1
    planning_mode: str = "heuristic_v1"
    source_screenplay_hash: str
    source_scene_ids: list[str] = Field(default_factory=list)
    max_panels_per_page: int


class LayoutPlan(BaseModel):
    schema_version: int = 1
    metadata: LayoutPlanMetadata
    beats: list[LayoutPlanBeatRef] = Field(default_factory=list)
    planned_panels: list[PlannedPanel] = Field(default_factory=list)
    planned_pages: list[PlannedPage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    user_overrides: dict[str, object] = Field(default_factory=dict)
    regeneration_impact: dict[str, str] = Field(default_factory=dict)
