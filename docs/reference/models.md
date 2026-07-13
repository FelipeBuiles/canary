# Models Reference

_Auto-generated from `models/*.py`. Do not edit manually._

These are the Pydantic models that flow between pipeline stages. `story_bible.json` carries the StoryBible. `panels/scene_NNN/panel_NNN.json` carries PanelBreakdown. `prompts/scene_NNN/panel_NNN.json` carries ImagePrompt. `assembly/pages/page_NNN.json` carries ComicPage.

## Bubble _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `type` | `Literal['speech', 'thought', 'narration']` | `'speech'` |
| `text` | `str` |  |
| `speaker_id` | `str | None` | `None` |
| `speaker_name` | `str | None` | `None` |
| `source_beat_id` | `str | None` | `None` |
| `source_text` | `str | None` | `None` |
| `narration_mode` | `str | None` | `None` |
| `preferred_zone` | `str | None` | `None` |
| `side` | `Literal['left', 'right', 'center']` | `'left'` |
| `full_width` | `bool | None` | `None` |
| `x` | `float | None` | `None` |
| `y` | `float | None` | `None` |
| `width` | `float | None` | `None` |
| `tail_x` | `float | None` | `None` |
| `tail_y` | `float | None` | `None` |
| `tail_direction` | `Literal['auto', 'up', 'down']` | `'auto'` |
| `font_family` | `str | None` | `None` |
| `font_size` | `int | None` | `None` |
| `font_color` | `str | None` | `None` |
| `fill_color` | `str | None` | `None` |
| `border_color` | `str | None` | `None` |
| `border_width` | `int | None` | `None` |

## Sfx _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` |  |
| `kind` | `SfxKind` | `'impact'` |
| `intensity` | `Literal[1, 2, 3]` | `2` |
| `anchor` | `SfxAnchor` | `'auto'` |
| `x` | `float | None` | `None` |
| `y` | `float | None` | `None` |
| `rotation` | `float` | `-4.0` |
| `font_size` | `int | None` | `None` |

## PagePanel _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `planned_panel_id` | `str | None` | `None` |
| `image_path` | `str` |  |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `importance` | `str | None` | `None` |
| `generation_mode` | `str | None` | `None` |
| `bubbles` | `list[Bubble]` | `Field(default_factory=list)` |
| `sfx` | `list[Sfx]` | `Field(default_factory=list)` |
| `image_offset_x` | `float | None` | `None` |
| `image_offset_y` | `float | None` | `None` |
| `grid_column` | `str | None` | `None` |
| `grid_row` | `str | None` | `None` |
| `x` | `float | None` | `None` |
| `y` | `float | None` | `None` |
| `width` | `float | None` | `None` |
| `height` | `float | None` | `None` |
| `clip_path` | `str | None` | `None` |
| `z_index` | `int | None` | `None` |
| `shape_intent` | `str | None` | `None` |

## ComicPage _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` |  |
| `source_page_id` | `str | None` | `None` |
| `layout` | `str` | `'4'` |
| `layout_mode` | `Literal['grid', 'freeform']` | `'grid'` |
| `panels` | `list[PagePanel]` | `Field(default_factory=list)` |

## LayoutPlanBeatRef _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `beat_id` | `str` |  |
| `scene_id` | `str` |  |
| `beat_index` | `int` |  |
| `type` | `str` |  |
| `character_id` | `str | None` | `None` |
| `content` | `str` |  |
| `source_text` | `str | None` | `None` |
| `direction` | `str | None` | `None` |
| `transition_type` | `str | None` | `None` |
| `narration_reason` | `str | None` | `None` |
| `emphasis_hint` | `str | None` | `None` |
| `shot_hint` | `str | None` | `None` |
| `transition_significance` | `str | None` | `None` |

## NarrationDecision _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `beat_id` | `str` |  |
| `scene_id` | `str` |  |
| `beat_index` | `int` |  |
| `source_text` | `str` |  |
| `caption_text` | `str | None` | `None` |
| `candidate_reason` | `str | None` | `None` |
| `decision` | `NarrationDecisionStatus` |  |
| `mode` | `NarrationMode | None` | `None` |
| `panel_id` | `str | None` | `None` |
| `preferred_zone` | `CaptionZone` | `'top'` |
| `decision_reason` | `str` |  |
| `fallback_decision` | `bool` | `False` |
| `caption_text_override` | `str | None` | `None` |

## PanelGeometry _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `panel_id` | `str` |  |
| `shape_intent` | `ShapeIntent` | `'rect'` |
| `region` | `list[float]` | `Field(default_factory=lambda: [0.0, 0.0, 1.0, 1...` |
| `polygon` | `list[list[float]]` | `Field(default_factory=list)` |
| `aspect_ratio` | `float | None` | `None` |
| `bleed` | `bool` | `False` |
| `z_index` | `int` | `0` |

## LLMPanelSpec _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `beat_indices` | `list[int]` |  |
| `characters_present` | `list[str]` | `Field(default_factory=list)` |
| `character_actions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `character_expressions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `key_objects` | `list[str]` | `Field(default_factory=list)` |
| `visual_requirements` | `list[str]` | `Field(default_factory=list)` |
| `shot_type` | `str` | `'medium'` |
| `camera_angle` | `str` | `'eye-level'` |
| `camera_note` | `str` | `''` |
| `lighting` | `str` | `''` |
| `mood` | `str` | `'neutral'` |
| `background_description` | `str` | `''` |
| `importance` | `PanelImportance` | `'standard'` |
| `shape_intent` | `ShapeIntent` | `'rect'` |
| `transition_out` | `str | None` | `None` |
| `page_break_after` | `bool` | `False` |
| `location_state_id` | `str | None` | `None` |

## LLMNarrationDecisionSpec _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `beat_index` | `int` |  |
| `decision` | `NarrationDecisionStatus` |  |
| `mode` | `NarrationMode | None` | `None` |
| `panel_index` | `int | None` | `None` |
| `preferred_zone` | `CaptionZone` | `'top'` |
| `decision_reason` | `str` |  |

## PlannedSfx _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` |  |
| `kind` | `SfxKind` | `'impact'` |
| `intensity` | `Literal[1, 2, 3]` | `2` |

## PlannedPanel _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `panel_id` | `str` |  |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `beat_ids` | `list[str]` | `Field(default_factory=list)` |
| `importance` | `PanelImportance` | `'standard'` |
| `shape_intent` | `ShapeIntent` | `'rect'` |
| `aspect_preference` | `float | None` | `None` |
| `aspect_range` | `list[float]` | `Field(default_factory=list)` |
| `generation_aspect_ratio` | `float | None` | `None` |
| `generation_width` | `int | None` | `None` |
| `generation_height` | `int | None` | `None` |
| `generation_shape` | `GenerationShape | None` | `None` |
| `generation_aspect_source` | `GenerationAspectSource | None` | `None` |
| `crop_policy` | `str` | `'flexible'` |
| `dialogue_load` | `int` | `0` |
| `caption_load` | `int` | `0` |
| `transition_in` | `str | None` | `None` |
| `transition_out` | `str | None` | `None` |
| `generation_mode` | `GenerationMode` | `'master'` |
| `image_fit_status` | `ImageFitStatus` | `'unknown'` |
| `regeneration_status` | `RegenerationStatus` | `'not_needed'` |
| `shot_type` | `str` | `'medium'` |
| `camera_angle` | `str` | `'eye-level'` |
| `characters_present` | `list[str]` | `Field(default_factory=list)` |
| `character_actions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `character_expressions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `character_positions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `key_objects` | `list[str]` | `Field(default_factory=list)` |
| `visual_requirements` | `list[str]` | `Field(default_factory=list)` |
| `background_description` | `str` | `''` |
| `camera_note` | `str` | `''` |
| `lighting` | `str` | `''` |
| `mood` | `str` | `''` |
| `dialogue` | `list[dict[str, str | None]]` | `Field(default_factory=list)` |
| `sfx` | `list[PlannedSfx]` | `Field(default_factory=list)` |
| `has_narration_caption` | `bool` | `False` |
| `narration_mode` | `NarrationMode | None` | `None` |
| `preferred_caption_zone` | `CaptionZone | None` | `None` |
| `page_break_after` | `bool` | `False` |
| `location_state_id` | `str | None` | `None` |

## PlannedPage _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_id` | `str` |  |
| `page_number` | `int` |  |
| `panel_ids` | `list[str]` | `Field(default_factory=list)` |
| `panel_geometries` | `list[PanelGeometry]` | `Field(default_factory=list)` |
| `scene_ids` | `list[str]` | `Field(default_factory=list)` |
| `scene_boundary_mode` | `SceneBoundaryMode` | `'scene_contained'` |
| `page_rhythm_role` | `PageRhythmRole` | `'regular'` |
| `layout_template` | `str` | `''` |
| `spread_id` | `str | None` | `None` |
| `cross_scene_reason` | `str | None` | `None` |

## LayoutPlanMetadata _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `planner_version` | `int` | `1` |
| `planning_mode` | `str` | `'llm_v1'` |
| `source_screenplay_hash` | `str` |  |
| `source_scene_ids` | `list[str]` | `Field(default_factory=list)` |
| `max_panels_per_page` | `int` |  |

## LayoutPlan _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `int` | `1` |
| `metadata` | `LayoutPlanMetadata` |  |
| `beats` | `list[LayoutPlanBeatRef]` | `Field(default_factory=list)` |
| `planned_panels` | `list[PlannedPanel]` | `Field(default_factory=list)` |
| `planned_pages` | `list[PlannedPage]` | `Field(default_factory=list)` |
| `narration_decisions` | `list[NarrationDecision]` | `Field(default_factory=list)` |
| `warnings` | `list[str]` | `Field(default_factory=list)` |
| `user_overrides` | `dict[str, object]` | `Field(default_factory=dict)` |
| `regeneration_impact` | `dict[str, str]` | `Field(default_factory=dict)` |

## LetteringStyle _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `mode` | `str` | `'auto'` |
| `preset` | `str | None` | `None` |
| `theme` | `str` | `'default'` |
| `font_pair` | `str` | `'golden-age'` |
| `vars` | `dict[str, str]` | `Field(default_factory=dict)` |
| `label` | `str` | `''` |
| `rationale` | `str` | `''` |
| `source` | `str` | `'fallback'` |
| `style_template_hash` | `str` | `''` |
| `generated_at` | `str` | `''` |

## DialogueLine _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `character_id` | `Optional[str]` | `None` |
| `text` | `str` |  |
| `type` | `str` |  |
| `source_beat_id` | `Optional[str]` | `None` |
| `source_text` | `Optional[str]` | `None` |
| `narration_mode` | `Optional[str]` | `None` |
| `preferred_zone` | `Optional[str]` | `None` |

## PanelBreakdown _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `shot_type` | `str` |  |
| `camera_angle` | `str` |  |
| `characters_present` | `list[str]` |  |
| `character_actions` | `dict[str, str]` |  |
| `character_expressions` | `dict[str, str]` |  |
| `character_positions` | `dict[str, str]` |  |
| `background_description` | `str` |  |
| `lighting` | `str` |  |
| `mood` | `str` |  |
| `dialogue` | `list[DialogueLine]` | `[]` |
| `sfx` | `list[str]` | `[]` |
| `transition_type` | `Optional[str]` | `None` |
| `transition_note` | `Optional[str]` | `None` |

## ScreenplayBeat _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `type` | `str` |  |
| `character_id` | `Optional[str]` | `None` |
| `content` | `str` |  |
| `source_text` | `Optional[str]` | `None` |
| `direction` | `Optional[str]` | `None` |
| `transition_type` | `Optional[str]` | `None` |
| `narration_reason` | `Optional[str]` | `None` |
| `location_state_id` | `Optional[str]` | `None` |

## Screenplay _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `scene_id` | `str` |  |
| `location_id` | `str` |  |
| `characters` | `list[str]` |  |
| `beats` | `list[ScreenplayBeat]` |  |

## LayoutBbox _(prompt.py)_

| Field | Type | Default |
|-------|------|---------|
| `x0` | `float` | `0.0` |
| `y0` | `float` | `0.0` |
| `x1` | `float` | `1.0` |
| `y1` | `float` | `1.0` |

## LayoutRegion _(prompt.py)_

| Field | Type | Default |
|-------|------|---------|
| `label` | `str` |  |
| `prompt` | `str` |  |
| `bbox` | `LayoutBbox` | `Field(default_factory=LayoutBbox)` |
| `reference_key` | `str | None` | `None` |

## PromptLayout _(prompt.py)_

| Field | Type | Default |
|-------|------|---------|
| `prompt` | `str | None` | `None` |
| `regions` | `list[LayoutRegion]` | `Field(default_factory=list)` |

## PromptSubject _(prompt.py)_

| Field | Type | Default |
|-------|------|---------|
| `character_id` | `str | None` | `None` |
| `name` | `str` |  |
| `identity` | `str` |  |
| `action` | `str` | `''` |
| `expression` | `str` | `''` |
| `position` | `str` | `''` |

## ImagePrompt _(prompt.py)_

| Field | Type | Default |
|-------|------|---------|
| `prompt_version` | `int` | `1` |
| `planned_panel_id` | `str | None` | `None` |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `generation_mode` | `str | None` | `None` |
| `shape_intent` | `str | None` | `None` |
| `generation_aspect_ratio` | `float | None` | `None` |
| `generation_width` | `int | None` | `None` |
| `generation_height` | `int | None` | `None` |
| `generation_shape` | `str | None` | `None` |
| `generation_aspect_source` | `str | None` | `None` |
| `crop_policy` | `str | None` | `None` |
| `transition_in` | `str | None` | `None` |
| `transition_out` | `str | None` | `None` |
| `location_state_id` | `str | None` | `None` |
| `has_narration_caption` | `bool` | `False` |
| `narration_mode` | `str | None` | `None` |
| `preferred_caption_zone` | `str | None` | `None` |
| `full_prompt` | `str` | `''` |
| `distilled_prompt` | `str | None` | `None` |
| `visual_brief` | `str | None` | `None` |
| `style` | `str | None` | `None` |
| `composition` | `str | None` | `None` |
| `setting` | `str | None` | `None` |
| `lighting` | `str | None` | `None` |
| `mood` | `str | None` | `None` |
| `subjects` | `list[PromptSubject]` | `Field(default_factory=list)` |
| `key_objects` | `list[str]` | `Field(default_factory=list)` |
| `visual_requirements` | `list[str]` | `Field(default_factory=list)` |
| `props` | `list[str]` | `Field(default_factory=list)` |
| `constraints` | `str | None` | `None` |
| `layout` | `PromptLayout | None` | `None` |
| `reference_image_paths` | `list[str]` | `Field(default_factory=list)` |
| `width` | `int` |  |
| `height` | `int` |  |
| `steps` | `int` |  |
| `continuity_note` | `str | None` | `None` |

## CharacterRelationship _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `character_id` | `str` |  |
| `relationship` | `str` |  |

## Character _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `age_range` | `str` |  |
| `gender` | `str` |  |
| `distinguishing_features` | `list[str]` |  |
| `default_outfit` | `str` |  |
| `relationships` | `list[CharacterRelationship]` | `[]` |
| `first_appearance_scene` | `str` |  |

## LocationState _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `description` | `Optional[str]` | `None` |

## Location _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `time_of_day` | `Optional[str]` | `None` |
| `mood` | `str` |  |
| `states` | `list[LocationState]` | `[]` |

## TransientObject _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `appears_in_beats` | `list[int]` | `[]` |

## Scene _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `chapter` | `int` |  |
| `title` | `str` |  |
| `location_id` | `str` |  |
| `character_ids` | `list[str]` |  |
| `summary` | `str` |  |
| `scene_type` | `str` |  |
| `narrative_beat` | `str` |  |
| `source_start_quote` | `str` |  |
| `character_appearances` | `dict[str, str]` | `{}` |
| `location_state_id` | `Optional[str]` | `None` |
| `transient_objects` | `list[TransientObject]` | `[]` |

## NarrativeArc _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `act` | `int` |  |
| `title` | `str` |  |
| `scenes` | `list[str]` |  |
| `turning_point` | `Optional[str]` | `None` |

## Prop _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `first_appearance_scene` | `Optional[str]` | `None` |

## StoryBible _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `title` | `str` |  |
| `author` | `str` |  |
| `total_scenes` | `int` |  |
| `characters` | `list[Character]` |  |
| `locations` | `list[Location]` |  |
| `scenes` | `list[Scene]` |  |
| `narrative_arcs` | `list[NarrativeArc]` |  |
| `style_notes` | `Optional[str]` | `None` |
| `props` | `list[Prop]` | `[]` |
