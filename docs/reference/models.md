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
| `side` | `Literal['left', 'right', 'center']` | `'left'` |
| `x` | `float | None` | `None` |
| `y` | `float | None` | `None` |
| `width` | `float | None` | `None` |

## Sfx _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` |  |
| `x` | `float | None` | `None` |
| `y` | `float | None` | `None` |
| `rotation` | `float` | `-4.0` |
| `font_size` | `int | None` | `None` |

## PagePanel _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `image_path` | `str` |  |
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `bubbles` | `list[Bubble]` | `Field(default_factory=list)` |
| `sfx` | `Sfx | None` | `None` |
| `grid_column` | `str | None` | `None` |
| `grid_row` | `str | None` | `None` |

## ComicPage _(comic_page.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` |  |
| `theme` | `str` | `'default'` |
| `layout` | `str` | `'4'` |
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
| `transition_note` | `Optional[str]` | `None` |

## ScreenplayBeat _(panel.py)_

| Field | Type | Default |
|-------|------|---------|
| `type` | `str` |  |
| `character_id` | `Optional[str]` | `None` |
| `content` | `str` |  |
| `direction` | `Optional[str]` | `None` |

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
| `scene_id` | `str` |  |
| `panel_number` | `int` |  |
| `full_prompt` | `str` |  |
| `reference_image_paths` | `list[str]` | `[]` |
| `negative_prompt` | `None` | `None` |
| `width` | `int` |  |
| `height` | `int` |  |
| `steps` | `int` |  |
| `guidance_scale` | `float` |  |

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

