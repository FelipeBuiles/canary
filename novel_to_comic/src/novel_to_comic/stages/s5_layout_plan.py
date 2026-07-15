"""Stage 5: Screenplay -> LayoutPlan JSON.

Calls the panel model once per scene to merge beats intelligently, vary shot
types, set lighting/mood, and flag page breaks. On validator rejection the
call is retried with the violation fed back to the model; persistent failures
raise.

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
import json
import logging
import math
import re
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.appearance import active_state, panel_position
from novel_to_comic.clients.structured_call import (
    StructuredCallError,
    generate_validated_json,
)
from novel_to_comic.usage import UsageRecord, estimate_text_cost
from novel_to_comic.config import Config
from novel_to_comic.events import make_progress
from novel_to_comic.layout_planning import (
    LAYOUT_PRESET_GEOMETRIES,
    select_layout_template,
    sync_narration_into_panels,
)
from novel_to_comic.models.comic_page import (
    infer_sfx_intensity,
    infer_sfx_kind,
    normalize_sfx_text,
)
from novel_to_comic.models.layout_plan import (
    LayoutPlan,
    LayoutPlanBeatRef,
    LayoutPlanMetadata,
    LLMNarrationDecisionSpec,
    LLMPanelSpec,
    NarrationDecision,
    PanelGeometry,
    PlannedPage,
    PlannedPanel,
    PlannedSfx,
)
from novel_to_comic.models.panel import DialogueLine, Screenplay, ScreenplayBeat
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.panel_aspect import (
    dimensions_for_generation_aspect,
    generation_shape_for_aspect,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.text_utils import clean, shorten


def _planned_sfx_from_beat(beat: ScreenplayBeat) -> PlannedSfx | None:
    text = normalize_sfx_text(beat.content)
    if not text:
        return None
    return PlannedSfx(
        text=text,
        kind=infer_sfx_kind(text),
        intensity=infer_sfx_intensity(text),
    )

console = Console()
logger = logging.getLogger("canary.plan")

# Safety caps on panel aggregation. These are upper bounds the LLM must respect;
# the prompt asks for restraint well below these values. Violations trigger a
# retry with the error fed back to the model, then deterministic auto-split as
# a last resort.
_MAX_VISUAL_PER_PANEL = 7
_MAX_DIALOGUE_PER_PANEL = 4
_MAX_DIALOGUE_WORDS_PER_PANEL = 30
_MAX_NARRATION_WORDS_PER_PANEL = 20

# Average beats per panel used to derive a concrete target panel count.
_BEATS_PER_PANEL_AVG = 3.0

# How many times to re-call the LLM with a corrective message before giving up.
# Each retry uses a higher temperature to escape repeated-answer loops.
_PLAN_RETRY_ATTEMPTS = 2
_PLAN_RETRY_TEMPERATURES = (0.4, 0.6, 0.8)

# ---------------------------------------------------------------------------
# System prompt for the LLM scene planner
# ---------------------------------------------------------------------------

_PLAN_SCENE_SYSTEM = """You are a comic book storyboard artist converting a screenplay scene into comic panels.

PRIMARY DIRECTIVE
-----------------
Produce approximately {target_panels} panels for this {visual_beat_count}-visual-beat scene.
The scene also has {narration_beat_count} narration candidate beat(s).
Aim for roughly {avg_per_panel} visual beats per panel: merge consecutive beats
when they share a moment, location, or exchange, and let a single beat stand
alone when it deserves emphasis. Use restraint -- the goal is a readable comic,
not a transcript.
Narration beats are adapted caption candidates with exact source provenance.
They should not inflate the panel target unless a caption_panel is genuinely needed.
Every non-narration beat must appear in exactly one panel's beat_indices. Do not skip beats.
If preserving the visual beats well requires more panels than the target, exceed the target.

WHEN TO MERGE
-------------
- 2-3 consecutive beats sharing the same moment, location, or exchange = often one panel.
- A short back-and-forth (2-3 short lines between the same characters) = often one panel.
- An action beat immediately followed by a brief reaction or short line = often one panel.
- LONG ANNOUNCEMENTS / MONOLOGUES (5+ consecutive lines from the same off-screen source):
  Group 2-3 announcement lines together with one character reaction per group.
  Show the character REACTING while the text plays.

HARD CEILINGS (absolute maximums -- panels exceeding these will be rejected):
- 7 visual beats per panel (action, dialogue, thought, sfx, transition)
- 4 dialogue/thought lines per panel
Hitting either ceiling means the panel is overloaded; split it.

PANEL FIELDS
------------
- characters_present: list character IDs visible in the panel. Empty = environment shot.
- character_actions: dict mapping character_id -> one short phrase describing body language
  or physical action (e.g. {{"char_001": "arms raised, turning in a slow circle"}}).
  REQUIRED for every character in characters_present. Describe posture, gesture, or
  movement -- not speech or emotion (those belong in expressions/mood).
- character_expressions: dict mapping character_id -> subtle specific facial expression
  for every visible character (e.g. {{"char_001": "eyes narrowed, mouth held still"}}).
- key_objects: list every plot-relevant visible object in the panel, including story props,
  held/touched/used objects, evidence, weapons, letters, doors, phones, flowers, etc.
  Do not list a carried/collected story prop just because similar raw material appears
  in the environment; wild flowers on the bank are not a carried Bundle of Flowers
  unless a character has actually gathered or is holding that bundle in this panel.
- visual_requirements: 1-4 concrete physical details from the covered beats that the
  generated image must show. Include action, expression, object, and spatial details.
  Do not include dialogue text, captions, labels, or SFX lettering here.
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
    "splash"   -- RARE full-page reveal reserved for the comic's biggest moments
                  (e.g. the inciting incident, a major reveal, the climax, the
                  final shot). Aim for 0-1 splashes per ACT, NOT per scene.
                  A typical comic has 3-4 splash panels total across the whole
                  book. A splash forces a single-panel page, so over-use
                  produces a comic where every other page is a single reveal.
    "hero"     -- the most prominent image in a scene; shares a page with
                  smaller follow-up panels via hero_top_N templates. Default
                  choice for scene-opening establishing shots (NOT splash).
    "accent"   -- emotional reaction or close-up
    "standard" -- everything else
- shape_intent: "wide"/"panorama" for vistas, "tall" for vertical action, "rect" otherwise.
- transition_out: in-scene only -- "smooth_continuation", "match_cut", "hard_cut", or null.
  Use "hard_cut" for any jump in time, place, or depicted reality, including flashbacks.
- page_break_after: true ONLY at a genuine narrative act-break (e.g. the scene's final
  panel if the scene ends a chapter). Most scenes: 0 page breaks. Maximum 1 per scene.
  Do NOT mark hero or accent panels with page_break_after just because they feel dramatic.

NARRATION DECISIONS
-------------------
Some beats may have type "narration". For those beats, content is the adapted caption text
and source_text is the exact source quote kept for provenance.
Decide what happens to every narration beat:
- rendered: the adapted caption appears later as a narration caption in Stage 8.
- visualized: the narration is intentionally handled by image/action/pacing, with no caption.
- dropped: the narration is intentionally omitted because it is redundant or weak. Use rarely.

For rendered narration, choose one mode:
- attached_caption: the quote overlays an existing visual panel.
- caption_panel: the narration motivates a distinct visual panel, usually establishing, transitional, or reflective.
Emit the mode value exactly as ``attached_caption`` or ``caption_panel`` -- do not
use synonyms such as ``overlay``, ``attached caption``, or ``separate panel``.
For visualized or dropped narration, emit ``mode: null``.

Rules:
- Use the narration beat's content as the caption text. Do not rewrite it here.
- Do not use source_text as the caption; source_text is only for review/provenance.
- Include rendered narration beat_indices in the panel that carries the caption.
- Prefer at most one narration caption per panel.
- Do not render text inside the image. Lettering happens later in compose.
- Use preferred_zone: top, bottom, left, right, overlay_center, or none.

Examples:
- Silent final turn: action beat "Myop lays down her flowers" + narration "And the summer was over."
  -> rendered, attached_caption, same final panel, preferred_zone top or bottom.
- Time/place bridge: narration "By twelve o'clock, her arms laden..." over a widening distance shot.
  -> rendered, caption_panel only if it needs its own establishing image.
- Visible scenery prose already carried by the image.
  -> visualized, reason says the panel shows it clearly.

OUTPUT FORMAT
-------------
Return {{"panels": [ {{...}}, ... ], "narration_decisions": [ {{...}}, ... ]}}.
Each panel object has exactly these keys:
  beat_indices, characters_present, character_actions, character_expressions,
  key_objects, visual_requirements, shot_type, camera_angle, camera_note, lighting,
  mood, background_description, importance, shape_intent, transition_out, page_break_after
Each narration_decisions object has exactly these keys:
  beat_index, decision, mode, panel_index, preferred_zone, decision_reason
For ``mode``, use only the exact machine values above or JSON ``null``.
"""


# ---------------------------------------------------------------------------
# Helpers shared by both planning modes
# ---------------------------------------------------------------------------

def _load_screenplay(project_dir: Path, scene_id: str) -> Screenplay:
    return artifacts.read_screenplay(project_dir, scene_id)


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
        source_text=beat.source_text,
        direction=beat.direction,
        transition_type=beat.transition_type,
        narration_reason=beat.narration_reason,
        emphasis_hint=emphasis_hint,
        shot_hint=shot_hint,
        transition_significance=transition_significance,
    )


def _narration_source_text(beat: ScreenplayBeat) -> str:
    return beat.source_text or beat.content


def _narration_caption_text(beat: ScreenplayBeat) -> str:
    return beat.content


def _is_dialogue_beat(beat: ScreenplayBeat) -> bool:
    """Thought beats occupy bubbles just like speech — count them together."""
    return beat.type in ("dialogue", "thought")


def _word_count(value: str | None) -> int:
    return len(re.findall(r"\S+", value or ""))


def _dialogue_word_count(beat: ScreenplayBeat) -> int:
    return _word_count(beat.content) if _is_dialogue_beat(beat) else 0


def _narration_word_count(beat: ScreenplayBeat) -> int:
    return _word_count(beat.content) if beat.type == "narration" else 0


def _dialogue_line(beat: ScreenplayBeat) -> list[dict[str, str | None]]:
    if _is_dialogue_beat(beat):
        return [DialogueLine(
            character_id=beat.character_id,
            text=beat.content,
            type="thought" if beat.type == "thought" else "speech",
        ).model_dump()]
    return []


def _compact_text(value: str | None, max_chars: int = 180) -> str:
    return shorten(clean(value or ""), max_chars).strip()


def _append_unique(items: list[str], value: str | None, *, max_chars: int = 180) -> None:
    text = _compact_text(value, max_chars)
    if not text:
        return
    if text.lower() in {item.lower() for item in items}:
        return
    items.append(text)


def _story_prop_lines(story_bible: StoryBible) -> list[str]:
    lines: list[str] = []
    for prop in getattr(story_bible, "props", []) or []:
        anchor = _compact_text(prop.visual_anchor, 180)
        label = f"{prop.id} ({prop.name})" if prop.id else prop.name
        lines.append(f"  {label}: {anchor}" if anchor else f"  {label}")
    return lines


def _character_name_lookup(story_bible: StoryBible) -> dict[str, str]:
    return {c.id: c.name for c in story_bible.characters}


def _beat_visual_requirement(
    beat: ScreenplayBeat,
    character_names: dict[str, str],
) -> str | None:
    if beat.type == "narration":
        return None
    content = _compact_text(beat.content, 180)
    direction = _compact_text(beat.direction, 250)

    def _name(char_id: str | None) -> str | None:
        if not char_id:
            return None
        return character_names.get(char_id, char_id)

    if beat.type == "action":
        actor = _name(beat.character_id)
        content_lower = content.lower()
        starts_with_actor = False
        if actor:
            actor_lower = actor.lower()
            actor_first_word = actor.split()[0].rstrip(",—")
            if content_lower.startswith(actor_lower):
                starts_with_actor = True
            elif actor_first_word and content_lower.startswith(actor_first_word.lower()):
                starts_with_actor = True

        pieces = [content] if starts_with_actor else [f"show {actor} {content}".strip() if actor else f"show {content}"]
        if direction:
            pieces.append(f"direction: {direction}")
        return "; ".join(piece for piece in pieces if piece)
    if beat.type == "dialogue":
        speaker = _name(beat.character_id) or "off-screen/unseen speaker"
        if direction:
            return f"show {speaker}'s dialogue moment through {direction}; no lettering"
        return (
            f"show {speaker}'s dialogue moment through physical "
            "body language or reaction; no lettering"
        )
    if beat.type == "thought":
        thinker = _name(beat.character_id) or "the character"
        if direction:
            return f"show {thinker}'s silent reflective moment through {direction}; no lettering"
        return (
            f"show {thinker}'s silent reflective moment through facial "
            "expression and posture; no lettering"
        )
    if beat.type == "sfx":
        return f"show the visible source or result of the {content} sound effect; no lettering"
    if beat.type == "transition":
        detail = direction or content
        return f"show the transition cue physically: {detail}"
    return f"show {content}"


def _visual_requirements_for_panel(
    spec: LLMPanelSpec,
    covered_pairs: list[tuple[int, ScreenplayBeat]],
    story_bible: StoryBible,
) -> list[str]:
    character_names = _character_name_lookup(story_bible)
    requirements: list[str] = []
    for _beat_index, beat in covered_pairs:
        _append_unique(requirements, _beat_visual_requirement(beat, character_names))
    for requirement in spec.visual_requirements:
        _append_unique(requirements, requirement)
    # Beat-derived requirements come first (they carry the story); cap tighter
    # on beat-heavy panels so the image prompt doesn't drown in must-shows.
    cap = 8 if len(covered_pairs) >= 5 else 12
    return requirements[:cap]


def _key_objects_for_panel(
    spec: LLMPanelSpec,
    covered_pairs: list[tuple[int, ScreenplayBeat]],
    story_bible: StoryBible,
) -> list[str]:
    objects: list[str] = []
    for item in spec.key_objects:
        _append_unique(objects, item, max_chars=120)

    blob_parts: list[str] = [
        spec.background_description,
        spec.camera_note,
        *spec.character_actions.values(),
        *spec.character_expressions.values(),
        *spec.key_objects,
        *spec.visual_requirements,
    ]
    for _idx, beat in covered_pairs:
        blob_parts.extend([beat.content, beat.direction or ""])
    blob = " ".join(clean(part or "") for part in blob_parts).lower()

    for prop in getattr(story_bible, "props", []) or []:
        name = (prop.name or "").strip()
        prop_id = (prop.id or "").strip()
        if not name and not prop_id:
            continue
        name_hit = bool(name and name.lower() in blob)
        id_hit = bool(prop_id and prop_id.lower() in blob)
        if name_hit or id_hit:
            _append_unique(objects, name or prop_id, max_chars=120)
    return objects


def _validate_llm_specs(specs: list[LLMPanelSpec], beats: list[ScreenplayBeat]) -> None:
    """Fail fast when the planner drops or duplicates visual beats."""
    visual_indices = {
        idx
        for idx, beat in enumerate(beats, start=1)
        if beat.type != "narration"
    }
    coverage = {idx: 0 for idx in visual_indices}

    for panel_number, spec in enumerate(specs, start=1):
        if not spec.beat_indices:
            raise ValueError(f"panel {panel_number} has no beat_indices")

        invalid = [idx for idx in spec.beat_indices if idx < 1 or idx > len(beats)]
        if invalid:
            raise ValueError(f"panel {panel_number} references invalid beat_indices: {invalid}")

        covered_visual = [
            idx for idx in spec.beat_indices
            if idx in visual_indices
        ]
        if len(covered_visual) > _MAX_VISUAL_PER_PANEL:
            raise ValueError(
                f"panel {panel_number} covers {len(covered_visual)} visual beats; "
                f"maximum is {_MAX_VISUAL_PER_PANEL}"
            )

        dialogue_count = sum(
            1
            for idx in spec.beat_indices
            if _is_dialogue_beat(beats[idx - 1])
        )
        if dialogue_count > _MAX_DIALOGUE_PER_PANEL:
            raise ValueError(
                f"panel {panel_number} covers {dialogue_count} dialogue beats; "
                f"maximum is {_MAX_DIALOGUE_PER_PANEL}"
            )

        dialogue_words = sum(_dialogue_word_count(beats[idx - 1]) for idx in spec.beat_indices)
        if dialogue_words > _MAX_DIALOGUE_WORDS_PER_PANEL:
            raise ValueError(
                f"panel {panel_number} contains {dialogue_words} dialogue words; "
                f"maximum is {_MAX_DIALOGUE_WORDS_PER_PANEL}"
            )

        narration_words = sum(_narration_word_count(beats[idx - 1]) for idx in spec.beat_indices)
        if narration_words > _MAX_NARRATION_WORDS_PER_PANEL:
            raise ValueError(
                f"panel {panel_number} contains {narration_words} narration words; "
                f"maximum is {_MAX_NARRATION_WORDS_PER_PANEL}"
            )

        for idx in covered_visual:
            coverage[idx] += 1

    missing = [idx for idx, count in coverage.items() if count == 0]
    duplicated = [idx for idx, count in coverage.items() if count > 1]
    if missing:
        raise ValueError(f"LLM plan omitted visual beat_indices: {missing}")
    if duplicated:
        raise ValueError(f"LLM plan duplicated visual beat_indices: {duplicated}")


def _normalize_spec_order(
    specs: list[LLMPanelSpec],
    narration_specs: list[LLMNarrationDecisionSpec],
) -> tuple[list[LLMPanelSpec], list[LLMNarrationDecisionSpec]]:
    """Restore story order the LLM occasionally scrambles.

    Beat indices within a panel are sorted (so dialogue reads in story order)
    and panels are stably reordered by their first covered beat (so reading
    order across panels follows the screenplay). Narration ``panel_index``
    references are remapped to follow their panels.
    """
    ordered_specs = [
        spec.model_copy(update={"beat_indices": sorted(spec.beat_indices)})
        for spec in specs
    ]
    order = sorted(
        range(len(ordered_specs)),
        key=lambda i: (
            min(ordered_specs[i].beat_indices) if ordered_specs[i].beat_indices else 0,
            i,
        ),
    )
    index_map = {old + 1: new + 1 for new, old in enumerate(order)}
    new_specs = [ordered_specs[i] for i in order]
    new_narration = [
        nspec.model_copy(update={"panel_index": index_map.get(nspec.panel_index, nspec.panel_index)})
        if nspec.panel_index is not None
        else nspec
        for nspec in narration_specs
    ]
    return new_specs, new_narration


def _aspect_for_shape(shape_intent: str) -> tuple[float, list[float]]:
    if shape_intent == "panorama":
        return 2.4, [2.0, 2.8]
    if shape_intent == "wide":
        return 1.8, [1.4, 2.2]
    if shape_intent == "tall":
        return 0.75, [0.55, 0.9]
    return 1.0, [0.8, 1.25]


def _generation_mode_for_shape(shape_intent: str, importance: str) -> str:
    if shape_intent in {"irregular", "bleed", "panorama"} or importance in {"hero", "splash"}:
        return "exact"
    return "master"


def _apply_generation_aspect_from_geometry(panel: PlannedPanel, geometry: PanelGeometry) -> None:
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
    The floor is clamped to the beat count: with exactly-once beat coverage
    a scene can never yield more panels than it has beats.
    """
    natural = math.ceil(beat_count / _BEATS_PER_PANEL_AVG)
    return max(min(4, beat_count), min(natural, config_max * 2))


def _visual_beat_count(beats: list[ScreenplayBeat]) -> int:
    return sum(1 for beat in beats if beat.type != "narration")


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
    prop_lines = "\n".join(_story_prop_lines(story_bible)) or "  (none)"

    if location:
        loc_text = f"{location.name}: {(location.visual_anchor or '')[:200]}"
    else:
        loc_text = screenplay.location_id

    # Location (and character) appearance state is resolved per panel from each
    # entity's appearance_timeline (novel_to_comic.appearance), so panels no
    # longer carry a location_state_id and the planner is not asked to tag it.

    beat_lines: list[str] = []
    for i, beat in enumerate(screenplay.beats, start=1):
        parts = [f"[{i}] ({beat.type})"]
        if beat.character_id:
            parts.append(f"char:{beat.character_id}")
        if beat.type == "narration":
            parts.append(f"caption:{beat.content!r}")
            parts.append(f"source_text:{_narration_source_text(beat)!r}")
        else:
            parts.append(f'"{beat.content}"')
        if beat.direction:
            parts.append(f"direction:{beat.direction!r}")
        if beat.transition_type:
            parts.append(f"transition:{beat.transition_type}")
        if beat.narration_reason:
            parts.append(f"narration_reason:{beat.narration_reason!r}")
        beat_lines.append(" ".join(parts))

    beat_count = len(screenplay.beats)
    return (
        f"Scene: {screenplay.scene_id}\n"
        f"Location: {loc_text}\n"
        f"Characters:\n{chars_lines}\n"
        f"Story props:\n{prop_lines}\n"
        f"Target: {target_panels} panels for {beat_count} beats "
        f"(~{beat_count/target_panels:.1f} beats per panel)\n\n"
        f"Beats ({beat_count} total):\n"
        + "\n".join(beat_lines)
    )


def _parse_llm_scene_plan(raw: dict) -> tuple[list[LLMPanelSpec], list[LLMNarrationDecisionSpec]]:
    """Validate and parse the raw LLM JSON response into LLMPanelSpec objects."""
    panels_raw = raw.get("panels")
    if not isinstance(panels_raw, list):
        raise ValueError(f"Expected {{'panels': [...]}} but got: {list(raw.keys())}")
    decisions_raw = raw.get("narration_decisions", [])
    if decisions_raw is None:
        decisions_raw = []
    if not isinstance(decisions_raw, list):
        raise ValueError("Expected narration_decisions to be a list")
    return (
        [LLMPanelSpec.model_validate(item) for item in panels_raw],
        [LLMNarrationDecisionSpec.model_validate(item) for item in decisions_raw],
    )


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


def _correction_user_content(
    base_user: str,
    previous_response: dict,
    error_message: str,
) -> str:
    """Build a follow-up user message that asks the model to fix its previous output."""
    try:
        prior = json.dumps(previous_response, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        prior = repr(previous_response)
    return (
        f"{base_user}\n\n"
        f"=== YOUR PREVIOUS RESPONSE WAS REJECTED ===\n"
        f"Validation error: {error_message}\n\n"
        f"Previous response:\n{prior}\n\n"
        f"Return a corrected JSON object with the same schema. Fix only what the "
        f"error describes; keep everything else consistent with the screenplay above."
    )


def _split_panel_to_caps(
    spec: LLMPanelSpec,
    beats: list[ScreenplayBeat],
) -> list[LLMPanelSpec]:
    """Split one over-cap LLMPanelSpec into chunks that each respect the caps.

    Greedy left-to-right walk through beat_indices: start a new chunk when
    adding the next beat would exceed either the visual or dialogue cap.
    Visual metadata (characters, mood, shot, etc.) is replicated to every
    chunk; only ``beat_indices`` differ.
    """
    chunks: list[list[int]] = [[]]
    visual_in_chunk = 0
    dialogue_in_chunk = 0
    dialogue_words_in_chunk = 0
    narration_words_in_chunk = 0
    for idx in spec.beat_indices:
        if 1 <= idx <= len(beats):
            beat = beats[idx - 1]
            adds_visual = 1 if beat.type != "narration" else 0
            adds_dialogue = 1 if _is_dialogue_beat(beat) else 0
            adds_dialogue_words = _dialogue_word_count(beat)
            adds_narration_words = _narration_word_count(beat)
        else:
            adds_visual = 0
            adds_dialogue = 0
            adds_dialogue_words = 0
            adds_narration_words = 0
        if chunks[-1] and (
            visual_in_chunk + adds_visual > _MAX_VISUAL_PER_PANEL
            or dialogue_in_chunk + adds_dialogue > _MAX_DIALOGUE_PER_PANEL
            or dialogue_words_in_chunk + adds_dialogue_words > _MAX_DIALOGUE_WORDS_PER_PANEL
            or narration_words_in_chunk + adds_narration_words > _MAX_NARRATION_WORDS_PER_PANEL
        ):
            chunks.append([])
            visual_in_chunk = 0
            dialogue_in_chunk = 0
            dialogue_words_in_chunk = 0
            narration_words_in_chunk = 0
        chunks[-1].append(idx)
        visual_in_chunk += adds_visual
        dialogue_in_chunk += adds_dialogue
        dialogue_words_in_chunk += adds_dialogue_words
        narration_words_in_chunk += adds_narration_words
    return [spec.model_copy(update={"beat_indices": chunk}) for chunk in chunks]


def _autosplit_overflow_panels(
    specs: list[LLMPanelSpec],
    narration_specs: list[LLMNarrationDecisionSpec],
    beats: list[ScreenplayBeat],
) -> tuple[list[LLMPanelSpec], list[LLMNarrationDecisionSpec], int]:
    """Split any cap-violating panels and remap narration panel_index to follow.

    Returns ``(new_panel_specs, new_narration_specs, num_panels_split)``.
    Non-violating panels pass through unchanged. Narration decisions whose
    ``panel_index`` referenced a split panel are remapped to the new panel
    that actually contains their narration beat.
    """
    new_specs: list[LLMPanelSpec] = []
    new_panel_beat_sets: list[set[int]] = []
    panels_split = 0
    for spec in specs:
        visual_count = sum(
            1 for idx in spec.beat_indices
            if 1 <= idx <= len(beats) and beats[idx - 1].type != "narration"
        )
        dialogue_count = sum(
            1 for idx in spec.beat_indices
            if 1 <= idx <= len(beats) and _is_dialogue_beat(beats[idx - 1])
        )
        dialogue_words = sum(
            _dialogue_word_count(beats[idx - 1])
            for idx in spec.beat_indices
            if 1 <= idx <= len(beats)
        )
        narration_words = sum(
            _narration_word_count(beats[idx - 1])
            for idx in spec.beat_indices
            if 1 <= idx <= len(beats)
        )
        if (
            visual_count > _MAX_VISUAL_PER_PANEL
            or dialogue_count > _MAX_DIALOGUE_PER_PANEL
            or dialogue_words > _MAX_DIALOGUE_WORDS_PER_PANEL
            or narration_words > _MAX_NARRATION_WORDS_PER_PANEL
        ):
            chunks = _split_panel_to_caps(spec, beats)
            new_specs.extend(chunks)
            for chunk in chunks:
                new_panel_beat_sets.append(set(chunk.beat_indices))
            panels_split += 1
        else:
            new_specs.append(spec)
            new_panel_beat_sets.append(set(spec.beat_indices))

    remapped_narration: list[LLMNarrationDecisionSpec] = []
    for nspec in narration_specs:
        new_panel_index = nspec.panel_index
        for i, beat_set in enumerate(new_panel_beat_sets, start=1):
            if nspec.beat_index in beat_set:
                new_panel_index = i
                break
        remapped_narration.append(nspec.model_copy(update={"panel_index": new_panel_index}))

    return new_specs, remapped_narration, panels_split


async def _plan_scene_llm(
    config: Config,
    screenplay: Screenplay,
    story_bible: StoryBible,
    warnings: list[str],
    usage_records: list[UsageRecord] | None = None,
) -> tuple[list[LLMPanelSpec], list[LLMNarrationDecisionSpec]]:
    """Call the panel model and validate its output, retrying on validation errors.

    The retry feeds the validation error back to the model along with its prior
    response so it can correct the specific violation. Each retry escalates the
    temperature to escape repeated-answer loops. If every retry still fails on
    cap violations and the last response parsed cleanly, the offending panels
    are auto-split deterministically and a warning is recorded. Only non-cap
    failures (parse errors, schema violations) raise after retries.
    """
    visual_beat_count = max(1, _visual_beat_count(screenplay.beats))
    narration_beat_count = sum(1 for beat in screenplay.beats if beat.type == "narration")
    target_panels = _target_panel_count(config.max_panels_per_scene, visual_beat_count)
    avg_per_panel = f"{visual_beat_count / target_panels:.1f}"
    system = _PLAN_SCENE_SYSTEM.format(
        target_panels=target_panels,
        beat_count=len(screenplay.beats),
        visual_beat_count=visual_beat_count,
        narration_beat_count=narration_beat_count,
        avg_per_panel=avg_per_panel,
    )
    base_user = _scene_planning_user_content(screenplay, story_bible, target_panels)

    def parse(raw: object) -> tuple[list[LLMPanelSpec], list[LLMNarrationDecisionSpec]]:
        specs, narration_specs = _parse_llm_scene_plan(raw)
        return _normalize_spec_order(specs, narration_specs)

    def validate(parsed: tuple[list[LLMPanelSpec], list[LLMNarrationDecisionSpec]]) -> None:
        specs, _ = parsed
        if not specs:
            raise ValueError("LLM returned empty panel list")
        _validate_llm_specs(specs, screenplay.beats)

    total_attempts = _PLAN_RETRY_ATTEMPTS + 1
    try:
        outcome = await generate_validated_json(
            config,
            model=config.effective_panel_model(),
            system_prompt=system,
            user_content=base_user,
            parse=parse,
            correction=lambda raw, exc: _correction_user_content(base_user, raw, str(exc)),
            label=f"LLM plan for {screenplay.scene_id}",
            feature="plan.scene_layout",
            max_output_tokens=16384,
            retries=_PLAN_RETRY_ATTEMPTS,
            temperatures=_PLAN_RETRY_TEMPERATURES,
            validate=validate,
        )
    except StructuredCallError as call_error:
        if usage_records is not None:
            usage_records.extend(call_error.usage_records)
        last_error = call_error.last_error
        last_parsed = call_error.last_parsed
    else:
        if usage_records is not None:
            usage_records.extend(outcome.usage_records)
        return outcome.value

    if last_parsed is not None:
        specs, narration_specs = last_parsed
        try:
            split_specs, split_narration, panels_split = _autosplit_overflow_panels(
                specs, narration_specs, screenplay.beats,
            )
            _validate_llm_specs(split_specs, screenplay.beats)
        except Exception as split_exc:
            logger.warning(
                "Auto-split for %s failed: %s",
                screenplay.scene_id, split_exc,
            )
        else:
            if panels_split > 0:
                msg = (
                    f"{screenplay.scene_id}: LLM exceeded panel caps after "
                    f"{total_attempts} attempts; auto-split {panels_split} panel(s) "
                    f"to recover."
                )
                warnings.append(msg)
                logger.warning(msg)
                return split_specs, split_narration

    assert last_error is not None
    raise ValueError(
        f"LLM planning for {screenplay.scene_id} failed after "
        f"{total_attempts} attempts: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# LLMPanelSpec -> PlannedPanel converter
# ---------------------------------------------------------------------------

def _llm_spec_to_planned_panel(
    scene_id: str,
    panel_index: int,
    spec: LLMPanelSpec,
    beats: list[ScreenplayBeat],
    story_bible: StoryBible,
) -> PlannedPanel:
    """Deterministically convert one LLMPanelSpec into a PlannedPanel."""
    covered_pairs = [
        (i, beats[i - 1])
        for i in spec.beat_indices
        if 0 < i <= len(beats)
    ]
    covered_beats = [beat for _idx, beat in covered_pairs]
    beat_ids = [_beat_id(scene_id, i) for i in spec.beat_indices if 0 < i <= len(beats)]

    # Aggregate dialogue lines, capped to prevent speech-bubble overflow.
    dialogue: list[dict[str, str | None]] = []
    for beat in covered_beats:
        dialogue.extend(_dialogue_line(beat))
        if len(dialogue) >= _MAX_DIALOGUE_PER_PANEL:
            break
    dialogue = dialogue[:_MAX_DIALOGUE_PER_PANEL]

    # SFX: collect every sfx beat in the covered set, preserving order.
    # Real panels often layer multiple sounds (impact + grunt, etc.).
    sfx_list: list[PlannedSfx] = []
    seen: set[str] = set()
    for b in covered_beats:
        if b.type != "sfx":
            continue
        planned = _planned_sfx_from_beat(b)
        if planned is None or planned.text in seen:
            continue
        sfx_list.append(planned)
        seen.add(planned.text)

    # Per-character metadata: prefer LLM-provided actions, fall back to beat-derived.
    # Action beats in screenplays frequently have character_id=null (narrator voice),
    # so beat-derived actions are sparse. The LLM fills this gap directly.
    character_actions: dict[str, str] = dict(spec.character_actions)
    character_expressions: dict[str, str] = dict(spec.character_expressions)
    for beat in covered_beats:
        cid = beat.character_id
        if not cid:
            continue
        if beat.type == "action" and cid not in character_actions:
            # Only use beat-derived action as fallback if LLM didn't provide one
            character_actions[cid] = beat.content
        elif beat.type == "dialogue":
            character_expressions.setdefault(cid, "speaking")
        elif beat.type == "thought":
            character_expressions.setdefault(cid, "lost in thought")

    dialogue_load = sum(1 for b in covered_beats if _is_dialogue_beat(b))
    caption_load = sum(
        1 for b in covered_beats
        if b.type == "action" and not b.character_id
    )
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
        character_positions={},  # filled scene-wide by _stabilize_character_positions

        key_objects=_key_objects_for_panel(spec, covered_pairs, story_bible),
        visual_requirements=_visual_requirements_for_panel(spec, covered_pairs, story_bible),
        background_description=spec.background_description,
        camera_note=spec.camera_note,
        lighting=spec.lighting,
        mood=spec.mood,
        dialogue=dialogue,
        sfx=sfx_list,
        page_break_after=spec.page_break_after,
    )


def _apply_screenplay_transition_boundaries(
    panels: list[PlannedPanel],
    beats: list[ScreenplayBeat],
) -> None:
    """Make explicit screenplay transitions authoritative at panel boundaries.

    The layout model decides where beats are grouped, but it must not downgrade
    a screenplay hard cut to a smooth continuation. A transition beat grouped
    with following visual beats applies to the boundary before that panel;
    otherwise it applies to the boundary after its owning panel.
    """
    owner_by_beat_id = {
        beat_id: panel_index
        for panel_index, panel in enumerate(panels)
        for beat_id in panel.beat_ids
    }
    beat_index_by_id = {
        _beat_id(panels[0].scene_id, index): index
        for index in range(1, len(beats) + 1)
    } if panels else {}

    for beat_index, beat in enumerate(beats, start=1):
        transition_type = (beat.transition_type or "").strip().lower()
        if beat.type != "transition" or not transition_type:
            continue
        owner_index = owner_by_beat_id.get(
            _beat_id(panels[0].scene_id, beat_index)
        ) if panels else None
        if owner_index is None:
            continue

        owner = panels[owner_index]
        has_following_visual_in_owner = any(
            beat_index_by_id.get(beat_id, 0) > beat_index
            and beats[beat_index_by_id[beat_id] - 1].type != "transition"
            for beat_id in owner.beat_ids
            if beat_id in beat_index_by_id
        )
        if has_following_visual_in_owner and owner_index > 0:
            before, after = panels[owner_index - 1], owner
        elif owner_index + 1 < len(panels):
            before, after = owner, panels[owner_index + 1]
        else:
            continue
        before.transition_out = transition_type
        after.transition_in = transition_type


def _build_narration_decisions(
    scene_id: str,
    specs: list[LLMNarrationDecisionSpec],
    panels: list[PlannedPanel],
    beats: list[ScreenplayBeat],
    warnings: list[str],
) -> list[NarrationDecision]:
    narration_by_index = {
        idx: beat
        for idx, beat in enumerate(beats, start=1)
        if beat.type == "narration"
    }
    panel_by_index = {panel.panel_number: panel for panel in panels}
    max_panel = max(panel_by_index) if panel_by_index else 0
    decisions: list[NarrationDecision] = []
    used: set[int] = set()

    for spec in specs:
        beat = narration_by_index.get(spec.beat_index)
        if beat is None:
            continue
        # Clamp panel_index to valid range before lookup
        raw_idx = spec.panel_index
        if raw_idx is not None and max_panel > 0:
            raw_idx = max(1, min(raw_idx, max_panel))
        panel = panel_by_index.get(raw_idx or -1)
        if spec.decision == "rendered" and panel is None:
            panel = panels[-1] if panels else None
            warnings.append(
                f"{scene_id}: narration beat {spec.beat_index} rendered without a valid panel; attached to final panel."
            )
        decisions.append(
            NarrationDecision(
                beat_id=_beat_id(scene_id, spec.beat_index),
                scene_id=scene_id,
                beat_index=spec.beat_index,
                source_text=_narration_source_text(beat),
                caption_text=_narration_caption_text(beat),
                candidate_reason=beat.narration_reason,
                decision=spec.decision,
                mode=spec.mode if spec.decision == "rendered" else None,
                panel_id=panel.panel_id if spec.decision == "rendered" and panel else None,
                preferred_zone=spec.preferred_zone,
                decision_reason=spec.decision_reason,
            )
        )
        used.add(spec.beat_index)

    for beat_index, beat in narration_by_index.items():
        if beat_index in used:
            continue
        panel = None
        for candidate in panels:
            if _beat_id(scene_id, beat_index) in candidate.beat_ids:
                panel = candidate
                break
        if panel is None and panels:
            panel = panels[-1]
        decision = NarrationDecision(
            beat_id=_beat_id(scene_id, beat_index),
            scene_id=scene_id,
            beat_index=beat_index,
            source_text=_narration_source_text(beat),
            caption_text=_narration_caption_text(beat),
            candidate_reason=beat.narration_reason,
            decision="rendered" if panel else "dropped",
            mode="attached_caption" if panel else None,
            panel_id=panel.panel_id if panel else None,
            preferred_zone="top",
            decision_reason=(
                "Fallback: Stage 3 selected this passage as necessary narration, "
                "and the planner did not provide a decision."
            ),
            fallback_decision=True,
        )
        decisions.append(decision)
        warnings.append(f'{scene_id}: fallback narration decision for "{beat.content}"')

    return decisions


def _stabilize_character_positions(panels: list[PlannedPanel]) -> None:
    """Assign each character a stable side for the whole scene.

    Per-panel left-to-right assignment from the LLM's arbitrary cast ordering
    flips characters between sides across consecutive panels (180-degree-rule
    violations) and drags speech-bubble sides along with it. Instead, each
    character gets a fixed side at first appearance in the scene; solo panels
    centre their subject.
    """
    side_by_char: dict[str, str] = {}
    _sides = ["left", "right", "center"]
    for panel in panels:
        for cid in panel.characters_present:
            if cid not in side_by_char:
                side_by_char[cid] = _sides[min(len(side_by_char), 2)]
    for panel in panels:
        if len(panel.characters_present) == 1:
            panel.character_positions = {panel.characters_present[0]: "center"}
        else:
            panel.character_positions = {
                cid: side_by_char[cid] for cid in panel.characters_present
            }


async def _plan_scene(
    config: Config,
    screenplay: Screenplay,
    story_bible: StoryBible,
    warnings: list[str],
    usage_records: list[UsageRecord] | None = None,
) -> tuple[list[PlannedPanel], list[NarrationDecision]]:
    """Plan one scene with the LLM, retrying on validation errors before raising."""
    location = next(
        (loc for loc in story_bible.locations if loc.id == screenplay.location_id),
        None,
    )
    loc_lighting = _location_lighting_hint(location.visual_anchor if location else "")

    specs, narration_specs = await _plan_scene_llm(
        config, screenplay, story_bible, warnings, usage_records=usage_records,
    )
    panels = [
        _llm_spec_to_planned_panel(screenplay.scene_id, idx, spec, screenplay.beats, story_bible)
        for idx, spec in enumerate(specs, start=1)
    ]
    _apply_screenplay_transition_boundaries(panels, screenplay.beats)
    decisions = _build_narration_decisions(
        screenplay.scene_id,
        narration_specs,
        panels,
        screenplay.beats,
        warnings,
    )
    panels = sync_narration_into_panels(panels, decisions)
    _stabilize_character_positions(panels)
    _apply_lighting_fallback(panels, loc_lighting)
    logger.info(
        "LLM planned %s: %d beats -> %d panels",
        screenplay.scene_id, len(screenplay.beats), len(panels),
    )
    return panels, decisions


# ---------------------------------------------------------------------------
# Quality post-processing: adjacent-panel dedup + scene overflow warning
# ---------------------------------------------------------------------------

# Upper bound for panels-per-scene. The extraction prompt asks for 3-8 panels
# per scene; doubling that gives generous headroom for action-heavy scenes
# while still flagging cases where a single scene has swallowed material from
# adjacent scenes.
_SCENE_PANEL_OVERFLOW_THRESHOLD = 16


def _panels_are_visually_duplicate(a: PlannedPanel, b: PlannedPanel) -> bool:
    """Return True when two consecutive panels would render to indistinguishable
    images. Same scene, same framing, same cast, same actions, same background.

    Used to collapse the LLM planner's occasional habit of emitting two
    near-identical panels back-to-back for related narration beats.
    """
    if a.scene_id != b.scene_id:
        return False
    if a.shot_type != b.shot_type:
        return False
    if a.characters_present != b.characters_present:
        return False
    if a.character_actions != b.character_actions:
        return False
    bg_a = (a.background_description or "").strip().lower()
    bg_b = (b.background_description or "").strip().lower()
    if bg_a != bg_b:
        return False
    # Merging must not recreate the bubble overflow the dialogue cap prevents.
    spoken = sum(
        1 for line in list(a.dialogue) + list(b.dialogue)
        if line.get("type") != "narration"
    )
    if spoken > _MAX_DIALOGUE_PER_PANEL:
        return False
    spoken_words = sum(
        _word_count(str(line.get("text") or ""))
        for line in list(a.dialogue) + list(b.dialogue)
        if line.get("type") != "narration"
    )
    if spoken_words > _MAX_DIALOGUE_WORDS_PER_PANEL:
        return False
    return True


def _dedupe_adjacent_panels(
    panels: list[PlannedPanel],
    narration_decisions: list[NarrationDecision],
    warnings: list[str],
) -> tuple[list[PlannedPanel], list[NarrationDecision]]:
    """Merge consecutive duplicate panels and remap narration references.

    Duplicate panels are merged into the earlier one, picking up the dropped
    panel's beat_ids, dialogue, and sfx so no narration content is lost.
    Any narration_decision whose panel_id pointed at the dropped panel is
    rewritten to point at the surviving merged panel.
    """
    if len(panels) < 2:
        return panels, narration_decisions

    panel_id_remap: dict[str, str] = {}
    kept: list[PlannedPanel] = [panels[0]]

    for current in panels[1:]:
        prev = kept[-1]
        if _panels_are_visually_duplicate(prev, current):
            for beat_id in current.beat_ids:
                if beat_id not in prev.beat_ids:
                    prev.beat_ids.append(beat_id)
            prev.dialogue = list(prev.dialogue) + list(current.dialogue)
            prev.sfx = list(prev.sfx) + list(current.sfx)
            if current.page_break_after:
                prev.page_break_after = True
            if current.transition_out:
                prev.transition_out = current.transition_out
            panel_id_remap[current.panel_id] = prev.panel_id
            warnings.append(
                f"{current.scene_id}: merged duplicate panel {current.panel_id} "
                f"into {prev.panel_id} (same shot, cast, action, background)"
            )
        else:
            kept.append(current)

    if not panel_id_remap:
        return kept, narration_decisions

    updated_decisions = [
        nd.model_copy(update={"panel_id": panel_id_remap[nd.panel_id]})
        if nd.panel_id in panel_id_remap
        else nd
        for nd in narration_decisions
    ]
    return kept, updated_decisions


# Narrative beats that justify keeping a splash. Each act's splash should be
# anchored on a scene whose narrative_beat is one of these, when possible.
_SPLASH_ELIGIBLE_BEATS: frozenset[str] = frozenset({
    "inciting_incident",
    "midpoint",
    "climax",
    "resolution",
})
_MAX_SPLASHES_PER_ACT = 1


def _demote_excess_splashes(
    panels: list[PlannedPanel],
    story_bible: StoryBible,
    warnings: list[str],
) -> list[PlannedPanel]:
    """Cap splash importance to at most one per narrative act.

    The planner is happy to mark every scene-opening shot as 'splash', but
    splashes force full-page layouts in the paginator. With many scenes that
    produces a comic where a third of the pages are single-panel openers.
    Demote the excess to 'hero' — which shares its page with follow-up
    panels via hero_top_N / splash+4 templates — and keep 'splash' only
    where the narrative beat genuinely warrants a full-page reveal.

    Selection rule per act:
      1. Prefer keeping splashes on scenes whose narrative_beat is one of
         {inciting_incident, midpoint, climax, resolution}.
      2. Break ties by scene order (the earlier one wins).
      3. Demote any extras to 'hero'; preserve their shape_intent (or
         upgrade rect -> wide so they remain the prominent slot on a
         hero_top_N page).

    Skipped silently when the bible has no narrative_arcs.
    """
    arcs = story_bible.narrative_arcs or []
    if not arcs:
        return panels

    scene_to_act: dict[str, int] = {}
    for arc in arcs:
        for scene_id in arc.scenes:
            scene_to_act[scene_id] = arc.act
    scene_to_beat: dict[str, str] = {
        s.id: (s.narrative_beat or "") for s in story_bible.scenes
    }

    splash_by_act: dict[int, list[PlannedPanel]] = {}
    for panel in panels:
        if panel.importance != "splash":
            continue
        act = scene_to_act.get(panel.scene_id)
        if act is None:
            continue
        splash_by_act.setdefault(act, []).append(panel)

    demote_ids: set[str] = set()
    for act, splash_panels in splash_by_act.items():
        if len(splash_panels) <= _MAX_SPLASHES_PER_ACT:
            continue
        def _rank(panel: PlannedPanel) -> tuple[int, int]:
            beat = scene_to_beat.get(panel.scene_id, "")
            eligible = 0 if beat in _SPLASH_ELIGIBLE_BEATS else 1
            return (eligible, panel.panel_number)
        ordered = sorted(splash_panels, key=_rank)
        for panel in ordered[_MAX_SPLASHES_PER_ACT:]:
            demote_ids.add(panel.panel_id)

    if not demote_ids:
        return panels

    out: list[PlannedPanel] = []
    for panel in panels:
        if panel.panel_id not in demote_ids:
            out.append(panel)
            continue
        new_shape = panel.shape_intent if panel.shape_intent != "rect" else "wide"
        out.append(panel.model_copy(update={
            "importance": "hero",
            "shape_intent": new_shape,
        }))
        warnings.append(
            f"{panel.scene_id}: demoted splash {panel.panel_id} to hero "
            "(act already has its allotted splash)."
        )
    return out


def _warn_scene_panel_overflow(
    panels: list[PlannedPanel],
    warnings: list[str],
) -> None:
    """Flag any scene whose panel count drastically exceeds the extraction
    prompt's 3-8 per-scene budget. A scene with >16 panels usually indicates
    that the adapt/screenplay stage extended the scene past its bible-defined
    boundary (e.g. swallowing the next scene's material).
    """
    from collections import Counter
    counts = Counter(p.scene_id for p in panels)
    for scene_id, count in counts.items():
        if count > _SCENE_PANEL_OVERFLOW_THRESHOLD:
            warnings.append(
                f"{scene_id}: planned {count} panels (>{_SCENE_PANEL_OVERFLOW_THRESHOLD}). "
                "This usually means the screenplay (adapt stage) overflowed the "
                "bible scene boundary. Check whether scene material that belongs "
                "to a later scene was bundled here, which causes downstream "
                "panels to inherit the wrong location anchor."
            )


# ---------------------------------------------------------------------------
# Cross-scene transition post-processing pass
# ---------------------------------------------------------------------------

def _cross_scene_transition_pass(
    panels: list[PlannedPanel],
    story_bible: StoryBible,
) -> list[PlannedPanel]:
    """Set transition_in / transition_out at every scene boundary.

    Same location AND same active location state on both sides ->
    smooth_continuation. Different location, or the same place in a different
    state (collapsed, burned, day -> night — i.e. a visible time/event jump)
    -> hard_cut. The active location state is resolved per panel from the
    location's appearance_timeline (novel_to_comic.appearance).
    """
    scene_order = [s.id for s in story_bible.scenes]
    loc_by_scene = {
        scene.id: next(
            (loc for loc in story_bible.locations if loc.id == scene.location_id), None
        )
        for scene in story_bible.scenes
    }

    def _effective_state(panel: PlannedPanel) -> str | None:
        loc = loc_by_scene.get(panel.scene_id)
        if loc is None:
            return None
        return active_state(
            loc.visual_anchor,
            loc.appearance_states,
            loc.appearance_timeline,
            panel_position(panel, scene_order),
            scene_order,
        ).state_id

    for i in range(len(panels) - 1):
        curr = panels[i]
        nxt = panels[i + 1]
        if curr.scene_id == nxt.scene_id:
            continue
        curr_loc = loc_by_scene.get(curr.scene_id)
        nxt_loc = loc_by_scene.get(nxt.scene_id)
        same_place = bool(curr_loc and nxt_loc and curr_loc.id == nxt_loc.id)
        same_state = _effective_state(curr) == _effective_state(nxt)
        if same_place and same_state:
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

# Largest layout preset holds 6 panels; chunks beyond that would stack
# panels onto the same template slot and render overlapped.
_MAX_TEMPLATE_CAPACITY = 6


def _split_run_evenly(run: list[PlannedPanel], max_per_page: int) -> list[list[PlannedPanel]]:
    """Split a run into near-equal chunks instead of greedy max-fill.

    Greedy filling turns 7 panels into a 6-panel page plus an orphan
    single-panel page that reads like an unintended splash; even splitting
    yields 4 + 3.
    """
    if not run:
        return []
    n_chunks = math.ceil(len(run) / max_per_page)
    base, extra = divmod(len(run), n_chunks)
    sizes = [base + (1 if i < extra else 0) for i in range(n_chunks)]
    chunks: list[list[PlannedPanel]] = []
    index = 0
    for size in sizes:
        chunks.append(run[index:index + size])
        index += size
    return chunks


def _importance_aware_paginate(
    scene_id: str,
    panels: list[PlannedPanel],
    start_page_number: int,
    max_per_page: int,
    scene_beat: str = "",
) -> list[PlannedPage]:
    """Group panels into pages using layout presets from LAYOUT_PRESET_GEOMETRIES.

    Respects:
    - Splash panels always occupy a page alone.
    - Hero panels start a new page so they land in the template's prominent
      first slot (templates assign slots by index).
    - page_break_after=True forces a page break after that panel.
    - max_per_page caps the chunk size (clamped to template capacity); runs
      longer than one page are split into near-equal chunks to avoid orphan
      single-panel pages.
    Template is selected by select_layout_template() based on count + importance.
    """
    max_per_page = min(max_per_page, _MAX_TEMPLATE_CAPACITY)

    # Build runs delimited by forced breaks: BEFORE hero/splash panels (so the
    # prominent panel leads its page) and AFTER splashes / page_break_after.
    runs: list[list[PlannedPanel]] = []
    current: list[PlannedPanel] = []
    for panel in panels:
        if panel.importance in {"splash", "hero"} and current:
            runs.append(current)
            current = []
        current.append(panel)
        if panel.importance == "splash" or panel.page_break_after:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    chunks: list[list[PlannedPanel]] = []
    for run in runs:
        chunks.extend(_split_run_evenly(run, max_per_page))

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
                geometry := PanelGeometry(
                    panel_id=panel.panel_id,
                    shape_intent=panel.shape_intent,
                    region=region,
                    polygon=polygon or [],
                    aspect_ratio=geom_aspect,
                    bleed=panel.shape_intent in {"bleed", "panorama"},
                    z_index=idx,
                )
            )
            # Keep panel.aspect_preference as the narrative shape requested by
            # planning, but store a separate canonical generation aspect from
            # the actual compose slot. Prompting and draw use this contract.
            _apply_generation_aspect_from_geometry(panel, geometry)

        # Rhythm comes from the narrative, not from hero presence (heroes are
        # routine scene openers): the book's first page is the intro, splash
        # pages and climax-beat scenes are climaxes, the rest is regular.
        if page_number == 1:
            rhythm = "intro"
        elif scene_beat == "climax" or any(p.importance == "splash" for p in chunk):
            rhythm = "climax"
        else:
            rhythm = "regular"

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
    scene_beat_map: dict[str, str] = {
        scene.id: scene.narrative_beat or "" for scene in story_bible.scenes
    }

    warnings: list[str] = []

    # -- Step 1: Plan each scene with the LLM in parallel ---------------------
    async def _plan_one(sp: Screenplay) -> tuple[str, list[PlannedPanel], list[NarrationDecision], list[LayoutPlanBeatRef]]:
        if not sp.beats:
            warnings.append(f"{sp.scene_id}: screenplay has no beats to plan")
            return sp.scene_id, [], [], []
        panels, narration_decisions = await _plan_scene(config, sp, story_bible, warnings, usage_records=usage_records)
        beat_refs = [
            _beat_ref(sp.scene_id, idx, beat)
            for idx, beat in enumerate(sp.beats, start=1)
        ]
        return sp.scene_id, panels, narration_decisions, beat_refs

    results = await asyncio.gather(*[_plan_one(sp) for sp in screenplays])

    # Flatten, preserving scene order
    all_beats: list[LayoutPlanBeatRef] = []
    all_panels: list[PlannedPanel] = []
    all_narration_decisions: list[NarrationDecision] = []
    panels_by_scene: dict[str, list[PlannedPanel]] = {}
    for _scene_id, panels, narration_decisions, beat_refs in results:
        all_beats.extend(beat_refs)
        all_panels.extend(panels)
        all_narration_decisions.extend(narration_decisions)
        panels_by_scene[_scene_id] = panels

    # -- Step 1.5: Dedup adjacent visually-identical panels + overflow warning --
    all_panels, all_narration_decisions = _dedupe_adjacent_panels(
        all_panels, all_narration_decisions, warnings
    )
    panels_by_scene = {sid: [] for sid in panels_by_scene}
    for panel in all_panels:
        panels_by_scene.setdefault(panel.scene_id, []).append(panel)
    _warn_scene_panel_overflow(all_panels, warnings)

    # -- Step 1.6: Cap splashes to one per narrative act ----------------------
    # The planner often marks every scene-opening shot as 'splash', which
    # forces a single-panel page per scene in the paginator. Demote excess
    # splashes to 'hero' so they share a page with follow-up panels.
    all_panels = _demote_excess_splashes(all_panels, story_bible, warnings)
    panels_by_scene = {sid: [] for sid in panels_by_scene}
    for panel in all_panels:
        panels_by_scene.setdefault(panel.scene_id, []).append(panel)

    # -- Step 2: Cross-scene transition pass -----------------------------------
    all_panels = _cross_scene_transition_pass(all_panels, story_bible)

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
            scene_beat=scene_beat_map.get(sp.scene_id, ""),
        )
        planned_pages.extend(pages)
        next_page_number += len(pages)

    return LayoutPlan(
        metadata=LayoutPlanMetadata(
            planning_mode="llm_v1",
            source_screenplay_hash=_screenplay_hash(screenplays),
            source_scene_ids=scene_ids,
            max_panels_per_page=config.max_panels_per_page,
        ),
        beats=all_beats,
        planned_panels=all_panels,
        planned_pages=planned_pages,
        narration_decisions=all_narration_decisions,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------

async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    scene_ids: list[str] | None = None,
) -> None:
    """Execute layout planning from screenplay artifacts."""
    story_bible = artifacts.read_story_bible(project_dir)
    ids = scene_ids or [scene.id for scene in story_bible.scenes]
    if config.dev_mode and not scene_ids:
        ids = ids[:1]
    # Pre-flight: verify all required screenplays exist.
    missing = [sid for sid in ids if not artifacts.screenplay_path(project_dir, sid).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing screenplays for {len(missing)} scene(s): "
            + ", ".join(missing)
            + ". Re-run the adapt stage first to generate them."
        )

    estimated = 0.0
    for sid in ids:
        sp_path = artifacts.screenplay_path(project_dir, sid)
        sp_text = sp_path.read_text() if sp_path.exists() else "x" * 4000
        estimated += estimate_text_cost(
            config.effective_panel_model(),
            _PLAN_SCENE_SYSTEM + "\n" + sp_text,
        )

    with ctx.execute(total=len(ids), estimated_cost_usd=estimated):
        with make_progress(ctx.on_event) as progress:
            task = progress.add_task("Layout planning", total=len(ids))
            usage_records: list[UsageRecord] = []
            plan = await _build_layout_plan(config, project_dir, story_bible, ids, usage_records=usage_records)
            artifacts.write_layout_plan(project_dir, plan)
            for usage in usage_records:
                ctx.record_api_usage(usage)
            for _scene_id in ids:
                ctx.record_item_done()
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)

        console.print(
            f"[green]Plan stage complete.[/green] Wrote "
            f"{artifacts.layout_plan_path(project_dir).relative_to(project_dir)} "
            f"with {len(plan.planned_panels)} planned panels across {len(plan.planned_pages)} pages."
            + (f" [yellow]({len(plan.warnings)} warning(s))[/yellow]" if plan.warnings else "")
        )
        ctx.log(
            f"Wrote {artifacts.layout_plan_path(project_dir).relative_to(project_dir)} "
            f"with {len(plan.planned_panels)} planned panels across {len(plan.planned_pages)} pages."
        )
        if plan.warnings:
            for warning in plan.warnings:
                ctx.log(warning, level="warning")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_text_cost

    story_bible = artifacts.read_story_bible_safe(project_dir)
    if story_bible is None:
        return 0.0

    total = 0.0
    for scene in story_bible.scenes:
        sp_path = project_dir / "screenplays" / f"{scene.id}.json"
        if not sp_path.exists():
            continue
        sp_text = ""
        try:
            sp_text = sp_path.read_text()
        except Exception:
            pass
        if not sp_text:
            sp_text = "x" * 4000
            
        total += estimate_text_cost(
            config.effective_panel_model(),
            _PLAN_SCENE_SYSTEM + "\n" + sp_text,
            output_chars=8000,
        )
    return total


STAGE = Stage(
    name="plan",
    run=run,
    outputs=lambda d: [d / "plan"],
    clean_paths=lambda d: clean_cascade(d, "plan"),
    estimate_cost=estimate_cost,
)
