# Models Reference

These are the Pydantic models that flow between pipeline stages.

- `story_bible.json` — carries the StoryBible (stage 1 output)
- `draw/panels/scene_NNN/panel_NNN.json` — carries PanelBreakdown (stage 5 output)
- `prompts/scene_NNN/panel_NNN.json` — carries ImagePrompt (stage 6 output)
- `compose/pages/page_NNN.json` — carries ComicPage (stage 8 output)
- `plan/layout_plan.json` — carries LayoutPlan (stage 4 output)

## Bubble _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `type` | `Literal["speech", "thought", "narration"]` | `"speech"` |
| `text` | `str` |  |
| `speaker_id` | `str \| None` | `None` |
| `speaker_name` | `str \| None` | `None` |
| `side` | `Literal["left", "right", "center"]` | `"left"` |
| `x` | `float \| None` | `None` |
| `y` | `float \| None` | `None` |
| `width` | `float \| None` | `None` |
| `tail_x` | `float \| None` | `None` |
| `tail_y` | `float \| None` | `None` |
| `tail_direction` | `Literal["auto", "up", "down"]` | `"auto"` |
| `font_family` | `str \| None` | `None` |
| `font_size` | `int \| None` | `None` |
| `font_color` | `str \| None` | `None` |
| `fill_color` | `str \| None` | `None` |
| `border_color` | `str \| None` | `None` |
| `border_width` | `int \| None` | `None` |
| `border_radius` | `int \| None` | `None` |

## Sfx _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` |  |
| `x` | `float \| None` | `None` |
| `y` | `float \| None` | `None` |
| `rotation` | `float` | `-4.0` |
| `font_size` | `int \| None` | `None` |

## PagePanel _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `planned_panel_id` | `str \| None` | `None` |
| `image_path` | `str` |  |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `importance` | `str \| None` | `None` |
| `generation_mode` | `str \| None` | `None` |
| `bubbles` | `list[Bubble]` | `Field(default_factory=list)` |
| `sfx` | `Sfx \| None` | `None` |
| `image_offset_x` | `float \| None` | `None` |
| `image_offset_y` | `float \| None` | `None` |
| `grid_column` | `str \| None` | `None` |
| `grid_row` | `str \| None` | `None` |
| `x` | `float \| None` | `None` |
| `y` | `float \| None` | `None` |
| `width` | `float \| None` | `None` |
| `height` | `float \| None` | `None` |
| `clip_path` | `str \| None` | `None` |
| `z_index` | `int \| None` | `None` |
| `shape_intent` | `str \| None` | `None` |

## ComicPage _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` |  |
| `source_page_id` | `str \| None` | `None` |
| `theme` | `str` | `"default"` |
| `layout` | `str` | `"4"` |
| `layout_mode` | `Literal["grid", "freeform"]` | `"grid"` |
| `style_vars` | `dict[str, str]` | `Field(default_factory=dict)` |
| `panels` | `list[PagePanel]` | `Field(default_factory=list)` |

## DialogueLine _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `character_id` | `Optional[str]` | `None` |
| `text` | `str` |  |
| `type` | `str` |  |

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
| `sfx` | `Optional[str]` | `None` |
| `transition_type` | `Optional[str]` | `None` |
| `transition_note` | `Optional[str]` | `None` |

## ScreenplayBeat _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `type` | `str` |  |
| `character_id` | `Optional[str]` | `None` |
| `content` | `str` |  |
| `direction` | `Optional[str]` | `None` |
| `transition_type` | `Optional[str]` | `None` |

## Screenplay _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `scene_id` | `str` |  |
| `location_id` | `str` |  |
| `characters` | `list[str]` |  |
| `beats` | `list[ScreenplayBeat]` |  |

## ImagePrompt _(prompt.py)_

| Field | Type | Default |
|-------|------|---------|
| `prompt_version` | `int` | `1` |
| `planned_panel_id` | `str \| None` | `None` |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `generation_mode` | `str \| None` | `None` |
| `shape_intent` | `str \| None` | `None` |
| `aspect_preference` | `float \| None` | `None` |
| `aspect_range` | `list[float]` | `Field(default_factory=list)` |
| `crop_policy` | `str \| None` | `None` |
| `transition_in` | `str \| None` | `None` |
| `transition_out` | `str \| None` | `None` |
| `full_prompt` | `str` | `""` |
| `style` | `str \| None` | `None` |
| `composition` | `str \| None` | `None` |
| `setting` | `str \| None` | `None` |
| `lighting` | `str \| None` | `None` |
| `mood` | `str \| None` | `None` |
| `subjects` | `list[PromptSubject]` | `Field(default_factory=list)` |
| `props` | `list[str]` | `Field(default_factory=list)` |
| `constraints` | `str \| None` | `None` |
| `reference_image_paths` | `list[str]` | `Field(default_factory=list)` |
| `negative_prompt` | `None` | `None` |
| `width` | `int` |  |
| `height` | `int` |  |
| `steps` | `int` |  |
| `guidance_scale` | `float` |  |
| `continuity_note` | `str \| None` | `None` |

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

## Location _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `time_of_day` | `Optional[str]` | `None` |
| `mood` | `str` |  |

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

## LayoutPlan _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `int` | `1` |
| `metadata` | `LayoutPlanMetadata` |  |
| `beats` | `list[LayoutPlanBeatRef]` | `Field(default_factory=list)` |
| `planned_panels` | `list[PlannedPanel]` | `Field(default_factory=list)` |
| `planned_pages` | `list[PlannedPage]` | `Field(default_factory=list)` |
| `warnings` | `list[str]` | `Field(default_factory=list)` |
| `user_overrides` | `dict[str, object]` | `Field(default_factory=dict)` |
| `regeneration_impact` | `dict[str, str]` | `Field(default_factory=dict)` |

### LayoutPlanMetadata _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `planner_version` | `int` | `1` |
| `planning_mode` | `str` | `"heuristic_v1"` |
| `source_screenplay_hash` | `str` |  |
| `source_scene_ids` | `list[str]` | `Field(default_factory=list)` |
| `max_panels_per_page` | `int` |  |

### LayoutPlanBeatRef _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `beat_id` | `str` |  |
| `scene_id` | `str` |  |
| `beat_index` | `int` |  |
| `type` | `str` |  |
| `character_id` | `str \| None` | `None` |
| `content` | `str` |  |
| `direction` | `str \| None` | `None` |
| `transition_type` | `str \| None` | `None` |
| `emphasis_hint` | `str \| None` | `None` |
| `shot_hint` | `str \| None` | `None` |
| `transition_significance` | `str \| None` | `None` |

### PlannedPanel _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `panel_id` | `str` |  |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `beat_ids` | `list[str]` | `Field(default_factory=list)` |
| `importance` | `PanelImportance` | `"standard"` |
| `shape_intent` | `ShapeIntent` | `"rect"` |
| `aspect_preference` | `float \| None` | `None` |
| `aspect_range` | `list[float]` | `Field(default_factory=list)` |
| `crop_policy` | `str` | `"flexible"` |
| `dialogue_load` | `int` | `0` |
| `caption_load` | `int` | `0` |
| `transition_in` | `str \| None` | `None` |
| `transition_out` | `str \| None` | `None` |
| `generation_mode` | `GenerationMode` | `"master"` |
| `image_fit_status` | `ImageFitStatus` | `"unknown"` |
| `regeneration_status` | `RegenerationStatus` | `"not_needed"` |
| `shot_type` | `str` | `"medium"` |
| `camera_angle` | `str` | `"eye-level"` |
| `characters_present` | `list[str]` | `Field(default_factory=list)` |
| `character_actions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `character_expressions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `character_positions` | `dict[str, str]` | `Field(default_factory=dict)` |
| `background_description` | `str` | `""` |
| `lighting` | `str` | `""` |
| `mood` | `str` | `""` |
| `dialogue` | `list[dict[str, str \| None]]` | `Field(default_factory=list)` |
| `sfx` | `str \| None` | `None` |

### PlannedPage _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_id` | `str` |  |
| `page_number` | `int` |  |
| `panel_ids` | `list[str]` | `Field(default_factory=list)` |
| `panel_geometries` | `list[PanelGeometry]` | `Field(default_factory=list)` |
| `scene_ids` | `list[str]` | `Field(default_factory=list)` |
| `scene_boundary_mode` | `SceneBoundaryMode` | `"scene_contained"` |
| `page_rhythm_role` | `PageRhythmRole` | `"regular"` |
| `spread_id` | `str \| None` | `None` |
| `cross_scene_reason` | `str \| None` | `None` |

### PanelGeometry _(layout_plan.py)_

| Field | Type | Default |
|-------|------|---------|
| `panel_id` | `str` |  |
| `shape_intent` | `ShapeIntent` | `"rect"` |
| `region` | `list[float]` | `Field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])` |
| `polygon` | `list[list[float]]` | `Field(default_factory=list)` |
| `aspect_ratio` | `float \| None` | `None` |
| `bleed` | `bool` | `False` |
| `z_index` | `int` | `0` |
