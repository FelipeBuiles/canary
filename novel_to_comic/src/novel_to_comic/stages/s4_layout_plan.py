"""Stage 4: Screenplay -> LayoutPlan JSON.

Two planning modes are supported, controlled by ``config.plan_mode``:

* ``"llm"``  -- calls Gemini Pro once per scene to merge beats intelligently,
               vary shot types, set lighting/mood, and flag page breaks.
               Falls back to heuristic for any scene where the LLM call fails.

* ``"heuristic"`` -- deterministic one-beat-per-panel mapper (original behaviour).

After scene planning, a cross-scene transition post-processing pass sets
``transition_in`` / ``transition_out`` at scene boundaries based on whether
consecutive scenes share the same location.

Finally, an importance-aware paginator groups panels into pages using the
templates in ``LAYOUT_PRESET_GEOMETRIES``, respecting ``page_break_after``
flags and giving hero/splash panels their own visual space.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from pathlib import Path

from rich.console import Console

from novel_to_comic.clients.text import generate_json
from novel_to_comic.usage import UsageRecord, estimate_text_cost
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.layout_planning import LAYOUT_PRESET_GEOMETRIES, select_layout_template
from novel_to_comic.models.layout_plan import (
    LayoutPlan,
    LayoutPlanBeatRef,
    LayoutPlanMetadata,
    LLMPanelSpec,
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
    record_api_usage,
    record_item_done,
    save_state,
)

console = Console()
logger = logging.getLogger("canary.plan")

# Maximum dialogue lines carried into a single PlannedPanel (safety cap on aggregation).
_MAX_DIALOGUE_PER_PANEL = 3

# Average beats per panel used to derive a concrete target panel count.
_BEATS_PER_PANEL_AVG = 3.0

# ---------------------------------------------------------------------------
# System prompt for the LLM scene planner
# ---------------------------------------------------------------------------

_PLAN_SCENE_SYSTEM = """You are a comic book storyboard artist converting a screenplay scene into comic panels.

PRIMARY DIRECTIVE
-----------------
Produce approximately {target_panels} panels for this {beat_count}-beat scene.
That means averaging {avg_per_panel} beats per panel -- you MUST merge consecutive beats.
One panel per beat is wrong. One panel per dialogue line is wrong.

HOW TO MERGE
------------
- 2-3 consecutive beats sharing the same moment, location, or exchange = one panel.
- A short back-and-forth dialogue (2-3 lines between the same characters) = one panel.
- An action beat immediately followed by a reaction or short line = one panel.
- LONG ANNOUNCEMENTS / MONOLOGUES (5+ consecutive lines from the same off-screen source):
  Group 2-3 announcement lines together with one character reaction per group.
  Show the character REACTING while the text plays. Pick representative lines -- you do
  not need to include every single line from the screenplay.

HARD CEILINGS (absolute maximums, only hit in genuinely extreme beats):
- 4 beats per panel
- 3 dialogue lines per panel

PANEL FIELDS
------------
- characters_present: list character IDs visible in the panel. Empty = environment shot.
- character_actions: dict mapping character_id -> one short phrase describing body language
  or physical action (e.g. {{"char_001": "arms raised, turning in a slow circle"}}).
  REQUIRED for every character in characters_present. Describe posture, gesture, or
  movement -- not speech or emotion (those belong in expressions/mood).
- background_description: panel-specific environmental DELTA from the location anchor
  (e.g. "smoldering debris left, boot prints in slush"). Leave empty if identical.
- camera_note: one concrete composition sentence
  (e.g. "Low angle looking up at the doorframe, figure in silhouette").
  Do NOT name a character if characters_present is empty.
- lighting: panel-specific (e.g. "cold blue moonlight"). REQUIRED -- if identical to the
  location default, write a short summary of that default (e.g. "shadowless white diffuse").
  Never leave blank.
- mood: 1-2 words (e.g. "dark comedic", "tense").
- shot_type: vary for visual rhythm -- never repeat the same type more than twice in a row.
  Use: close-up, medium, wide, over-shoulder, extreme-wide.
- importance:
    "splash"   -- scene-opening establishing shot (at most 1 per scene)
    "hero"     -- single most climactic image in the scene (at most 1 per scene)
    "accent"   -- emotional reaction or close-up
    "standard" -- everything else
- shape_intent: "wide"/"panorama" for vistas, "tall" for vertical action, "rect" otherwise.
- transition_out: in-scene only -- "smooth_continuation", "match_cut", or null.
- page_break_after: true ONLY at a genuine narrative act-break (e.g. the scene's final
  panel if the scene ends a chapter). Most scenes: 0 page breaks. Maximum 1 per scene.
  Do NOT mark hero or accent panels with page_break_after just because they feel dramatic.

OUTPUT FORMAT
-------------
Return {{"panels": [ {{...}}, ... ]}} where each object has exactly these keys:
  beat_indices, characters_present, character_actions, shot_type, camera_angle,
  camera_note, lighting, mood, background_description, importance, shape_intent,
  transition_out, page_break_after
"""


# ---------------------------------------------------------------------------
# Helpers shared by both planning modes
# ---------------------------------------------------------------------------

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


def _dialogue_line(beat: ScreenplayBeat) -> list[dict[str, str | None]]:
    if beat.type != "dialogue":
        return []
    return [DialogueLine(
        character_id=beat.character_id,
        text=beat.content,
        type="speech",
    ).model_dump()]


def _aspect_for_shape(shape_intent: str) -> tuple[float, list[float]]:
    if shape_intent == "wide":
        return 1.8, [1.4, 2.2]
    if shape_intent in {"tall", "panorama"}:
        return 0.75, [0.55, 0.9]
    return 1.0, [0.8, 1.25]


def _generation_mode_for_shape(shape_intent: str, importance: str) -> str:
    if shape_intent in {"irregular", "bleed", "panorama"} or importance in {"hero", "splash"}:
        return "exact"
    return "master"


_LIGHTING_KEYWORDS = frozenset({
    "lighting", "light", "glow", "shadow", "diffuse", "ambient", "moonlight",
    "sunlight", "fluorescent", "candlelight", "backlit", "silhouette", "neon",
    "dramatic", "overcast", "dawn", "dusk", "rim light", "flat light",
})


def _location_lighting_hint(visual_anchor: str) -> str:
    """Extract lighting-relevant tags from a Danbooru-style location visual_anchor."""
    tags = [t.strip() for t in visual_anchor.split(",")]
    lighting_tags = [
        t for t in tags
        if any(kw in t.lower() for kw in _LIGHTING_KEYWORDS)
    ]
    return ", ".join(lighting_tags) if lighting_tags else ""


def _target_panel_count(config_max: int, beat_count: int) -> int:
    """Compute a concrete target panel count for a scene.

    For short-to-medium scenes the configured max is the ceiling.
    For very long scenes (more beats than config_max * avg) the target
    scales up, capped at 2x the configured max to avoid runaway expansion.
    """
    natural = math.ceil(beat_count / _BEATS_PER_PANEL_AVG)
    return max(4, min(natural, config_max * 2))


# ---------------------------------------------------------------------------
# Heuristic planner (original one-beat-per-panel logic, kept as fallback)
# ---------------------------------------------------------------------------

def _shot_type_for_beat(beat: ScreenplayBeat) -> str:
    if beat.type == "transition":
        return "wide"
    if beat.type == "dialogue":
        return "medium"
    content = beat.content.lower()
    if any(w in content for w in ("close", "whisper", "tear", "blink")):
        return "close-up"
    if any(w in content for w in ("crowd", "city", "landscape", "room")):
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
    if any(w in content for w in ("tower", "stairs", "fall", "drop")):
        return "tall"
    if any(w in content for w in ("horizon", "street", "field", "landscape")):
        return "wide"
    return "rect"


def _importance_for_beat(beat: ScreenplayBeat) -> str:
    if beat.type == "transition":
        return "hero"
    if beat.type == "sfx":
        return "accent"
    return "standard"


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
    character_expressions: dict[str, str] = {}
    if beat.character_id and beat.type == "dialogue":
        character_expressions[beat.character_id] = "speaking"
    character_positions = {beat.character_id: "center"} if beat.character_id else {}
    dialogue_load = 1 if beat.type == "dialogue" else 0
    caption_load = 1 if beat.type == "action" and not beat.character_id else 0
    aspect_preference, aspect_range = _aspect_for_shape(shape_intent)
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
        camera_note=beat.direction or "",
        lighting="",
        mood="tense" if beat.type == "transition" else "neutral",
        dialogue=_dialogue_line(beat),
        sfx=beat.content if beat.type == "sfx" else None,
    )


def _plan_scene_heuristic(
    screenplay: Screenplay,
    scene_location_name: str,
) -> list[PlannedPanel]:
    return [
        _panel_from_beat(screenplay.scene_id, beat_index, beat, scene_location_name)
        for beat_index, beat in enumerate(screenplay.beats, start=1)
    ]


# ---------------------------------------------------------------------------
# LLM planner
# ---------------------------------------------------------------------------

def _scene_planning_user_content(
    screenplay: Screenplay,
    story_bible: StoryBible,
    target_panels: int,
) -> str:
    """Build the user message for the LLM scene planning call."""
    char_by_id = {c.id: c for c in story_bible.characters}
    scene_chars = [char_by_id[cid] for cid in screenplay.characters if cid in char_by_id]
    location = next((loc for loc in story_bible.locations if loc.id == screenplay.location_id), None)

    chars_lines = "\n".join(
        f"  {c.id} ({c.name}): {(c.visual_anchor or '')[:140]}"
        for c in scene_chars
    ) or "  (none)"

    if location:
        loc_text = f"{location.name}: {(location.visual_anchor or '')[:200]}"
    else:
        loc_text = screenplay.location_id

    beat_lines: list[str] = []
    for i, beat in enumerate(screenplay.beats, start=1):
        parts = [f"[{i}] ({beat.type})"]
        if beat.character_id:
            parts.append(f"char:{beat.character_id}")
        parts.append(f'"{beat.content}"')
        if beat.direction:
            parts.append(f"direction:{beat.direction!r}")
        if beat.transition_type:
            parts.append(f"transition:{beat.transition_type}")
        beat_lines.append(" ".join(parts))

    beat_count = len(screenplay.beats)
    return (
        f"Scene: {screenplay.scene_id}\n"
        f"Location: {loc_text}\n"
        f"Characters:\n{chars_lines}\n"
        f"Target: {target_panels} panels for {beat_count} beats "
        f"(~{beat_count/target_panels:.1f} beats per panel)\n\n"
        f"Beats ({beat_count} total):\n"
        + "\n".join(beat_lines)
    )


def _parse_llm_panel_specs(raw: dict) -> list[LLMPanelSpec]:
    """Validate and parse the raw LLM JSON response into LLMPanelSpec objects."""
    panels_raw = raw.get("panels")
    if not isinstance(panels_raw, list):
        raise ValueError(f"Expected {{'panels': [...]}} but got: {list(raw.keys())}")
    return [LLMPanelSpec.model_validate(item) for item in panels_raw]


def _apply_lighting_fallback(
    panels: list[PlannedPanel],
    location_lighting_hint: str,
) -> None:
    """Fill in empty lighting on panels using the location hint."""
    if not location_lighting_hint:
        return
    for panel in panels:
        if not panel.lighting:
            panel.lighting = location_lighting_hint


async def _plan_scene_llm(
    config: Config,
    screenplay: Screenplay,
    story_bible: StoryBible,
    usage_records: list[UsageRecord] | None = None,
) -> list[LLMPanelSpec]:
    """Call the panel model to produce panel specs for a single scene."""
    beat_count = len(screenplay.beats)
    target_panels = _target_panel_count(config.max_panels_per_scene, beat_count)
    avg_per_panel = f"{beat_count / target_panels:.1f}"
    system = _PLAN_SCENE_SYSTEM.format(
        target_panels=target_panels,
        beat_count=beat_count,
        avg_per_panel=avg_per_panel,
    )
    user = _scene_planning_user_content(screenplay, story_bible, target_panels)
    api_result = await generate_json(
        config,
        model=config.effective_panel_model(),
        system_prompt=system,
        user_content=user,
        temperature=0.4,
        max_output_tokens=16384,
        feature="plan.scene_layout",
    )
    if usage_records is not None and api_result.usage is not None:
        usage_records.append(api_result.usage)
    return _parse_llm_panel_specs(api_result.value)


# ---------------------------------------------------------------------------
# LLMPanelSpec -> PlannedPanel converter
# ---------------------------------------------------------------------------

def _llm_spec_to_planned_panel(
    scene_id: str,
    panel_index: int,
    spec: LLMPanelSpec,
    beats: list[ScreenplayBeat],
) -> PlannedPanel:
    """Deterministically convert one LLMPanelSpec into a PlannedPanel."""
    covered_beats = [beats[i - 1] for i in spec.beat_indices if 0 < i <= len(beats)]
    beat_ids = [_beat_id(scene_id, i) for i in spec.beat_indices if 0 < i <= len(beats)]

    # Aggregate dialogue lines, capped to prevent speech-bubble overflow.
    dialogue: list[dict[str, str | None]] = []
    for beat in covered_beats:
        dialogue.extend(_dialogue_line(beat))
        if len(dialogue) >= _MAX_DIALOGUE_PER_PANEL:
            break
    dialogue = dialogue[:_MAX_DIALOGUE_PER_PANEL]

    # SFX: use the last SFX beat in the covered set
    sfx = next((b.content for b in reversed(covered_beats) if b.type == "sfx"), None)

    # Per-character metadata: prefer LLM-provided actions, fall back to beat-derived.
    # Action beats in screenplays frequently have character_id=null (narrator voice),
    # so beat-derived actions are sparse. The LLM fills this gap directly.
    character_actions: dict[str, str] = dict(spec.character_actions)
    character_expressions: dict[str, str] = {}
    for beat in covered_beats:
        cid = beat.character_id
        if not cid:
            continue
        if beat.type == "action" and cid not in character_actions:
            # Only use beat-derived action as fallback if LLM didn't provide one
            character_actions[cid] = beat.content
        elif beat.type == "dialogue":
            character_expressions[cid] = "speaking"

    # Spread characters left -> center -> right
    character_positions: dict[str, str] = {}
    chars = spec.characters_present
    _pos_map = ["left", "center", "right"]
    for i, cid in enumerate(chars):
        if len(chars) == 1:
            character_positions[cid] = "center"
        elif len(chars) == 2:
            character_positions[cid] = "left" if i == 0 else "right"
        else:
            character_positions[cid] = _pos_map[min(i, 2)]

    dialogue_load = sum(1 for b in covered_beats if b.type == "dialogue")
    caption_load = sum(1 for b in covered_beats if b.type == "action" and not b.character_id)
    aspect_preference, aspect_range = _aspect_for_shape(spec.shape_intent)

    return PlannedPanel(
        panel_id=_panel_id(scene_id, panel_index),
        scene_id=scene_id,
        panel_number=panel_index,
        beat_ids=beat_ids,
        importance=spec.importance,
        shape_intent=spec.shape_intent,
        aspect_preference=aspect_preference,
        aspect_range=aspect_range,
        crop_policy="flexible" if spec.shape_intent == "rect" else "preserve_subject",
        dialogue_load=dialogue_load,
        caption_load=caption_load,
        transition_in=None,      # filled by cross-scene pass
        transition_out=spec.transition_out,
        generation_mode=_generation_mode_for_shape(spec.shape_intent, spec.importance),
        shot_type=spec.shot_type,
        camera_angle=spec.camera_angle,
        characters_present=spec.characters_present,
        character_actions=character_actions,
        character_expressions=character_expressions,
        character_positions=character_positions,
        background_description=spec.background_description,
        camera_note=spec.camera_note,
        lighting=spec.lighting,
        mood=spec.mood,
        dialogue=dialogue,
        sfx=sfx,
        page_break_after=spec.page_break_after,
    )


async def _plan_scene(
    config: Config,
    screenplay: Screenplay,
    story_bible: StoryBible,
    scene_location_name: str,
    warnings: list[str],
    usage_records: list[UsageRecord] | None = None,
) -> list[PlannedPanel]:
    """Plan one scene, using the LLM if plan_mode='llm', else heuristic.

    Falls back to heuristic automatically on LLM error.
    """
    location = next(
        (loc for loc in story_bible.locations if loc.id == screenplay.location_id),
        None,
    )
    loc_lighting = _location_lighting_hint(location.visual_anchor if location else "")

    if config.plan_mode == "heuristic":
        return _plan_scene_heuristic(screenplay, scene_location_name)

    try:
        specs = await _plan_scene_llm(config, screenplay, story_bible, usage_records=usage_records)
        if not specs:
            raise ValueError("LLM returned empty panel list")
        panels = [
            _llm_spec_to_planned_panel(screenplay.scene_id, idx, spec, screenplay.beats)
            for idx, spec in enumerate(specs, start=1)
        ]
        _apply_lighting_fallback(panels, loc_lighting)
        logger.info(
            "LLM planned %s: %d beats -> %d panels",
            screenplay.scene_id, len(screenplay.beats), len(panels),
        )
        return panels
    except Exception as exc:
        warnings.append(
            f"{screenplay.scene_id}: LLM planning failed ({exc!s}), falling back to heuristic"
        )
        logger.warning("LLM planning failed for %s: %s", screenplay.scene_id, exc)
        return _plan_scene_heuristic(screenplay, scene_location_name)


# ---------------------------------------------------------------------------
# Cross-scene transition post-processing pass
# ---------------------------------------------------------------------------

def _cross_scene_transition_pass(
    panels: list[PlannedPanel],
    scene_location_map: dict[str, str],
) -> list[PlannedPanel]:
    """Set transition_in / transition_out at every scene boundary.

    Same location on both sides -> smooth_continuation.
    Different location -> hard_cut.
    """
    for i in range(len(panels) - 1):
        curr = panels[i]
        nxt = panels[i + 1]
        if curr.scene_id == nxt.scene_id:
            continue
        curr_loc = scene_location_map.get(curr.scene_id)
        nxt_loc = scene_location_map.get(nxt.scene_id)
        if curr_loc and nxt_loc and curr_loc == nxt_loc:
            curr.transition_out = "smooth_continuation"
            nxt.transition_in = "smooth_continuation"
        else:
            if not curr.transition_out:
                curr.transition_out = "hard_cut"
            nxt.transition_in = "hard_cut"
    return panels


# ---------------------------------------------------------------------------
# Importance-aware paginator
# ---------------------------------------------------------------------------

def _importance_aware_paginate(
    scene_id: str,
    panels: list[PlannedPanel],
    start_page_number: int,
    max_per_page: int,
) -> list[PlannedPage]:
    """Group panels into pages using layout presets from LAYOUT_PRESET_GEOMETRIES.

    Respects:
    - Splash panels always start a new page (and occupy it alone).
    - page_break_after=True forces a page break after that panel.
    - max_per_page caps the chunk size.
    Template is selected by select_layout_template() based on count + importance.
    """
    chunks: list[list[PlannedPanel]] = []
    current: list[PlannedPanel] = []

    for panel in panels:
        # Splash panels always stand alone
        if panel.importance == "splash" and current:
            chunks.append(current)
            current = []
        current.append(panel)
        if panel.importance == "splash" or panel.page_break_after or len(current) >= max_per_page:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)

    pages: list[PlannedPage] = []
    page_number = start_page_number

    for chunk in chunks:
        template_name = select_layout_template(chunk)
        template = LAYOUT_PRESET_GEOMETRIES.get(template_name)
        if template is None or len(template) < len(chunk):
            # Graceful fallback: use the largest available template
            template_name = "2x3"
            template = LAYOUT_PRESET_GEOMETRIES["2x3"]

        geometries: list[PanelGeometry] = []
        for idx, panel in enumerate(chunk):
            region, polygon = template[min(idx, len(template) - 1)]
            geom_aspect = (region[2] / region[3]) if region[3] else None
            geometries.append(
                PanelGeometry(
                    panel_id=panel.panel_id,
                    shape_intent=panel.shape_intent,
                    region=region,
                    polygon=polygon or [],
                    aspect_ratio=geom_aspect,
                    bleed=panel.shape_intent in {"bleed", "panorama"},
                    z_index=idx,
                )
            )
            if geom_aspect is not None and abs(geom_aspect - (panel.aspect_preference or 1.0)) > 0.1:
                panel.aspect_preference = geom_aspect

        is_intro = page_number == start_page_number
        has_climax = any(p.importance in {"hero", "splash"} for p in chunk)
        rhythm = "intro" if is_intro else ("climax" if has_climax else "regular")

        pages.append(
            PlannedPage(
                page_id=_page_id(page_number),
                page_number=page_number,
                panel_ids=[p.panel_id for p in chunk],
                panel_geometries=geometries,
                scene_ids=[scene_id],
                scene_boundary_mode="scene_contained",
                page_rhythm_role=rhythm,
                layout_template=template_name,
            )
        )
        page_number += 1

    return pages


# ---------------------------------------------------------------------------
# Top-level build function
# ---------------------------------------------------------------------------

async def _build_layout_plan(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    scene_ids: list[str],
    usage_records: list[UsageRecord] | None = None,
) -> LayoutPlan:
    screenplays = [_load_screenplay(project_dir, scene_id) for scene_id in scene_ids]
    location_name_by_id = {loc.id: loc.name for loc in story_bible.locations}
    scene_location_map = {sp.scene_id: sp.location_id for sp in screenplays}

    warnings: list[str] = []

    # -- Step 1: Plan each scene (LLM or heuristic) in parallel ---------------
    async def _plan_one(sp: Screenplay) -> tuple[str, list[PlannedPanel], list[LayoutPlanBeatRef]]:
        loc_name = location_name_by_id.get(sp.location_id, sp.location_id)
        if not sp.beats:
            warnings.append(f"{sp.scene_id}: screenplay has no beats to plan")
            return sp.scene_id, [], []
        panels = await _plan_scene(config, sp, story_bible, loc_name, warnings, usage_records=usage_records)
        beat_refs = [
            _beat_ref(sp.scene_id, idx, beat)
            for idx, beat in enumerate(sp.beats, start=1)
        ]
        return sp.scene_id, panels, beat_refs

    results = await asyncio.gather(*[_plan_one(sp) for sp in screenplays])

    # Flatten, preserving scene order
    all_beats: list[LayoutPlanBeatRef] = []
    all_panels: list[PlannedPanel] = []
    panels_by_scene: dict[str, list[PlannedPanel]] = {}
    for _scene_id, panels, beat_refs in results:
        all_beats.extend(beat_refs)
        all_panels.extend(panels)
        panels_by_scene[_scene_id] = panels

    # -- Step 2: Cross-scene transition pass -----------------------------------
    all_panels = _cross_scene_transition_pass(all_panels, scene_location_map)

    # -- Step 3: Importance-aware pagination per scene -------------------------
    planned_pages: list[PlannedPage] = []
    next_page_number = 1
    for sp in screenplays:
        scene_panels = panels_by_scene.get(sp.scene_id, [])
        if not scene_panels:
            continue
        pages = _importance_aware_paginate(
            sp.scene_id,
            scene_panels,
            start_page_number=next_page_number,
            max_per_page=max(1, config.max_panels_per_page),
        )
        planned_pages.extend(pages)
        next_page_number += len(pages)

    return LayoutPlan(
        metadata=LayoutPlanMetadata(
            planning_mode=f"{config.plan_mode}_v1",
            source_screenplay_hash=_screenplay_hash(screenplays),
            source_scene_ids=scene_ids,
            max_panels_per_page=config.max_panels_per_page,
        ),
        beats=all_beats,
        planned_panels=all_panels,
        planned_pages=planned_pages,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------

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
    if config.dev_mode and not scene_ids:
        ids = ids[:1]
    layout_plan_dir = project_dir / "plan"
    layout_plan_path = layout_plan_dir / "layout_plan.json"

    # Pre-flight: verify all required screenplays exist.
    missing = [sid for sid in ids if not (project_dir / "screenplays" / f"{sid}.json").exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing screenplays for {len(missing)} scene(s): "
            + ", ".join(missing)
            + ". Re-run the adapt stage first to generate them."
        )

    estimated = 0.0
    for sid in ids:
        sp_path = project_dir / "screenplays" / f"{sid}.json"
        sp_text = sp_path.read_text() if sp_path.exists() else "x" * 4000
        estimated += estimate_text_cost(
            config.effective_panel_model(),
            _PLAN_SCENE_SYSTEM + "\n" + sp_text,
        )
    begin_stage(state, "plan", total=len(ids), estimated_cost_usd=estimated)
    emit({"type": "stage_begin", "stage": "plan", "total": len(ids)})
    save_state(state, project_dir)

    try:
        with make_progress(on_event) as progress:
            task = progress.add_task("Layout planning", total=len(ids))
            usage_records: list[UsageRecord] = []
            plan = await _build_layout_plan(config, project_dir, story_bible, ids, usage_records=usage_records)
            layout_plan_dir.mkdir(parents=True, exist_ok=True)
            layout_plan_path.write_text(plan.model_dump_json(indent=2))
            for usage in usage_records:
                record_api_usage(state, "plan", usage)
            for _scene_id in ids:
                record_item_done(state, "plan")
                emit(
                    {
                        "type": "stage_progress",
                        "stage": "plan",
                        "done": state.stages["plan"].items_done,
                        "total": state.stages["plan"].items_total,
                    }
                )
                progress.advance(task)

        complete_stage(state, "plan")
        emit(
            {
                "type": "stage_complete",
                "stage": "plan",
                "done": state.stages["plan"].items_done,
                "total": state.stages["plan"].items_total,
            }
        )
        save_state(state, project_dir)
        console.print(
            f"[green]Stage 4 complete.[/green] Wrote "
            f"{layout_plan_path.relative_to(project_dir)} "
            f"with {len(plan.planned_panels)} planned panels across {len(plan.planned_pages)} pages."
            + (f" [yellow]({len(plan.warnings)} warning(s))[/yellow]" if plan.warnings else "")
        )
        emit(
            {
                "type": "log",
                "stage": "plan",
                "level": "info",
                "message": (
                    f"Wrote {layout_plan_path.relative_to(project_dir)} "
                    f"with {len(plan.planned_panels)} planned panels across {len(plan.planned_pages)} pages."
                ),
            }
        )
        if plan.warnings:
            for warning in plan.warnings:
                emit({"type": "log", "stage": "plan", "level": "warning", "message": warning})

    except Exception as exc:
        fail_stage(state, "plan", str(exc))
        emit({"type": "stage_fail", "stage": "plan", "message": str(exc)})
        save_state(state, project_dir)
        raise
