"""Prompt assembly — single path from PlannedPanel or ImagePrompt to rendered body.

Both the direct stage (s6_storyboard) and the edit route (stages.update_prompt)
used to call separate functions, risking drift in how the narration-caption
constraint note is applied.  This module is the single owner of that logic:
callers get one function for the build path and one for the re-render path, both
backed by the same constraint normalisation.

Slice 03 adds deterministic source lineage. ``compute_source_sha256`` projects a
sorted, stable view of the Story Bible + PlannedPanel + appearance-state inputs
that feed the canonical prompt, and ``prompt_is_current`` is now content-based:
a stored prompt is current when its recorded ``source_sha256`` matches a fresh
build from the current inputs. User corrections are stored as overlays
(``ImagePrompt.user_overlays``) and replayed over a fresh canonical build, so a
rebuild preserves valid edits instead of being suppressed.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt, OverlayWarning, PromptLayout, PromptOverlayOp
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import (
    IMAGE_PROMPT_VERSION,
    _render_panel_prompt_body_parts,
    build_planned_panel_prompt_spec,
    ensure_distilled_prompt,
    generate_distilled_prompt,
    visual_brief_source_spec,
)
from novel_to_comic.panel_aspect import dimensions_for_reve_layout

logger = logging.getLogger(__name__)

_NARRATION_NOTE = (
    "narration caption will be lettered in post-production only; "
    "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
)


def _apply_narration_constraint(constraints: str | None, has_narration_caption: bool) -> str | None:
    """Return constraints with the narration note present iff has_narration_caption.

    Idempotent — safe to call whether or not the note is already embedded
    in the stored constraints string.
    """
    base = (constraints or "").replace(f"; {_NARRATION_NOTE}", "").replace(_NARRATION_NOTE, "").strip("; ")
    if not has_narration_caption:
        return base or None
    return f"{base}; {_NARRATION_NOTE}" if base else _NARRATION_NOTE


def assemble_panel_prompt(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None = None,
) -> ImagePrompt:
    """Build an ImagePrompt from a PlannedPanel.

    Calls through to ``build_planned_panel_prompt_spec`` in prompting.py and
    records the deterministic ``source_sha256``. The returned prompt has
    ``full_prompt`` set; call ``ensure_distilled_prompt`` afterwards if a
    distilled version is needed before saving.
    """
    prompt = build_planned_panel_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
    prompt.source_sha256 = compute_source_sha256(
        config, project_dir, panel, story_bible, prev_panel
    )
    return prompt


def compute_source_sha256(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None = None,
) -> str:
    """Public source-hash for one panel's canonical prompt inputs.

    Excludes generation-time-only inputs (active style text) and reference
    materialization (owned by Slice 04). See ``_source_inputs_hash``.
    """
    return _source_inputs_hash(config, project_dir, panel, story_bible, prev_panel)


# ── Slice 03: deterministic source lineage ───────────────────────────────────


def _source_inputs_hash(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None,
) -> str:
    """SHA-256 of the canonical source projection for one panel.

    The projection is the sorted, stable JSON view of every input
    ``build_planned_panel_prompt_spec`` consumes: the relevant PlannedPanel
    visual fields, prior-panel continuity inputs, referenced character records
    and appearance timelines, the active location record and timeline, matched
    prop records, the canonical prompt schema/version, target language, and
    continuity mode. Two builds from identical inputs yield the same hash.

    Generation-time-only inputs (active style text) are deliberately excluded:
    changing the selected style must not rebuild stored panel structure. Matched
    prop/character presence is derived inside the projection from the Story
    Bible, so it is covered indirectly through the entity records plus the panel
    text that drives matching.
    """
    projection = _source_projection(config, panel, story_bible, prev_panel)
    payload = json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_projection(
    config: Config,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None,
) -> dict:
    """Sorted, stable dict of the canonical source inputs for one panel.

    Field order within dicts is fixed; keys are sorted at hash time. Only
    inputs that affect the canonical compiled prompt are included — derived
    fields (``full_prompt``, ``distilled_prompt``, ``visual_brief``, layout,
    dimensions emitted by ``panel_aspect``) and generation-time overlays
    (active style text) are excluded.
    """
    scene_order = [s.id for s in story_bible.scenes]
    scene = next((s for s in story_bible.scenes if s.id == panel.scene_id), None)
    location = None
    if scene:
        location = next(
            (loc for loc in story_bible.locations if loc.id == scene.location_id), None
        )

    characters_present = [
        c for c in story_bible.characters
        if c.id in set(getattr(panel, "characters_present", []) or [])
    ]
    # Sort by id for determinism independent of list order in the Story Bible.
    characters_present.sort(key=lambda c: c.id)

    # Matched props: recompute the same presence test the builder uses so a
    # prop record change (or the panel text that drives a match) is covered.
    matched_prop_ids = _matched_prop_ids_for_panel(panel, story_bible, scene_order)
    matched_props = [p for p in (story_bible.props or []) if p.id in matched_prop_ids]
    matched_props.sort(key=lambda p: p.id)

    character_projections = [
        {
            "id": c.id,
            "name": c.name,
            "visual_anchor": c.visual_anchor,
            "default_outfit": c.default_outfit,
            "distinguishing_features": list(c.distinguishing_features or []),
            "appearance_states": [
                {
                    "id": s.id,
                    "label": s.label,
                    "visual_anchor": s.visual_anchor,
                    "visually_significant": s.visually_significant,
                    "canonical_equivalent": s.canonical_equivalent,
                    "continuity_guard": s.continuity_guard,
                }
                for s in (c.appearance_states or [])
            ],
            "appearance_timeline": [
                {
                    "state_id": a.state_id,
                    "scene_id": a.at.scene_id,
                    "beat": a.at.beat,
                }
                for a in (c.appearance_timeline or [])
            ],
        }
        for c in characters_present
    ]

    location_projection = None
    if location is not None:
        location_projection = {
            "id": location.id,
            "name": location.name,
            "visual_anchor": location.visual_anchor,
            "time_of_day": location.time_of_day,
            "mood": location.mood,
            "appearance_states": [
                {
                    "id": s.id,
                    "label": s.label,
                    "visual_anchor": s.visual_anchor,
                    "visually_significant": s.visually_significant,
                    "canonical_equivalent": s.canonical_equivalent,
                    "continuity_guard": s.continuity_guard,
                }
                for s in (location.appearance_states or [])
            ],
            "appearance_timeline": [
                {
                    "state_id": a.state_id,
                    "scene_id": a.at.scene_id,
                    "beat": a.at.beat,
                }
                for a in (location.appearance_timeline or [])
            ],
        }

    prop_projections = [
        {
            "id": p.id,
            "name": p.name,
            "visual_anchor": p.visual_anchor,
            "first_appearance_scene": p.first_appearance_scene,
        }
        for p in matched_props
    ]

    return {
        "schema_version": IMAGE_PROMPT_VERSION,
        "target_language": config.language_code(),
        "continuity_mode": getattr(config, "continuity_mode", "hybrid"),
        "panel": {
            "panel_id": panel.panel_id,
            "scene_id": panel.scene_id,
            "panel_number": panel.panel_number,
            "beat_ids": list(getattr(panel, "beat_ids", []) or []),
            "importance": panel.importance,
            "shape_intent": panel.shape_intent,
            "crop_policy": panel.crop_policy,
            "generation_mode": panel.generation_mode,
            "shot_type": panel.shot_type,
            "camera_angle": panel.camera_angle,
            "camera_note": panel.camera_note,
            "background_description": panel.background_description,
            "lighting": panel.lighting,
            "mood": panel.mood,
            "has_narration_caption": panel.has_narration_caption,
            "narration_mode": panel.narration_mode,
            "preferred_caption_zone": panel.preferred_caption_zone,
            "transition_in": panel.transition_in,
            "transition_out": panel.transition_out,
            "characters_present": sorted(set(panel.characters_present or [])),
            "character_actions": _sorted_str_dict(panel.character_actions),
            "character_expressions": _sorted_str_dict(panel.character_expressions),
            "character_positions": _sorted_str_dict(panel.character_positions),
            "key_objects": list(panel.key_objects or []),
            "visual_requirements": list(panel.visual_requirements or []),
            "dialogue_text": _dialogue_texts(panel),
            "sfx_text": [s.text for s in (panel.sfx or [])],
            "aspect_preference": panel.aspect_preference,
        },
        "prev_continuity": _prev_continuity_projection(prev_panel, story_bible),
        "characters": character_projections,
        "location": location_projection,
        "scene_location_id": (scene.location_id if scene else None),
        "scene_order": list(scene_order),
        "matched_props": prop_projections,
    }


def _sorted_str_dict(values: dict[str, str] | None) -> list[tuple[str, str]]:
    """Deterministic list-of-pairs for a string→string dict."""
    return sorted(
        ((str(k), str(v)) for k, v in (values or {}).items()),
        key=lambda kv: kv[0],
    )


def _dialogue_texts(panel: PlannedPanel) -> list[str]:
    return [
        str(line.get("text", ""))
        for line in (panel.dialogue or [])
        if line.get("text")
    ]


def _prev_continuity_projection(
    prev_panel: PlannedPanel | None, story_bible: StoryBible
) -> dict | None:
    """Project the prior-panel continuity inputs.

    The builder only synthesizes a continuity note for smooth/match-cut
    transitions; its content derives from the previous panel's transition type
    plus the action/expression/position state of its present characters. Those
    are the only prev-panel fields that affect the canonical prompt.
    """
    if prev_panel is None:
        return None
    soft_continuity = {"smooth_continuation", "match_cut"}
    transition_type = (prev_panel.transition_out or "").strip().lower()
    if transition_type not in soft_continuity:
        return None
    character_names = {c.id: c.name for c in story_bible.characters}
    present = sorted(set(prev_panel.characters_present or []))
    actions = {
        cid: prev_panel.character_actions.get(cid, "")
        for cid in present
    }
    expressions = {
        cid: prev_panel.character_expressions.get(cid, "")
        for cid in present
    }
    positions = {
        cid: prev_panel.character_positions.get(cid, "")
        for cid in present
    }
    return {
        "transition_out": transition_type,
        "characters_present": present,
        "character_names": {cid: character_names.get(cid, cid) for cid in present},
        "character_actions": actions,
        "character_expressions": expressions,
        "character_positions": positions,
    }


def _matched_prop_ids_for_panel(
    panel: PlannedPanel, story_bible: StoryBible, scene_order
) -> set[str]:
    """Recompute the matched prop ids the builder would select for this panel."""
    from novel_to_comic.prompting import _props_present_in_panel

    matched = _props_present_in_panel(
        panel, story_bible, scene_order=scene_order,
    )
    return {p.id for p in matched if p.id}


def reapply_overlays(
    prompt: ImagePrompt, overlays: list[PromptOverlayOp]
) -> list[OverlayWarning]:
    """Reapply user overlay ops onto ``prompt`` in place; return drop warnings.

    Each op is keyed to the entity id and appearance/location state in which it
    was authored. Subject-scoped ops reapply only to the matching subject AND a
    compatible state (``None`` state is state-neutral and always re-apes when
    the subject is present). Ops whose target subject disappeared or whose state
    is incompatible are dropped with a structured warning rather than misapplied
    to a different subject index or state.

    Returns the list of warnings so callers can log/report them. Overlays that
    reapplly successfully are also recorded on ``prompt.user_overlays`` so the
    lineage is preserved across the rebuild.
    """
    warnings: list[OverlayWarning] = []
    reapplied: list[PromptOverlayOp] = []
    subject_fields = {"action", "expression", "position"}

    for op in overlays:
        value = op.value
        if isinstance(value, list):
            value = [item.strip() for item in value if item.strip()]
        else:
            value = (value or "").strip()
        if not value:
            warnings.append(OverlayWarning(
                code="value_empty",
                reason="Overlay value is empty after trimming; nothing to apply.",
                operation=op,
            ))
            continue

        if op.field in subject_fields:
            subject = _find_subject_for_overlay(prompt, op)
            if subject is None:
                warnings.append(OverlayWarning(
                    code="subject_missing",
                    reason=(
                        f"Overlay targets character {op.subject_character_id!r} which is "
                        "no longer present in this panel."
                    ),
                    operation=op,
                ))
                continue
            if not _subject_state_compatible(subject, op):
                warnings.append(OverlayWarning(
                    code="state_incompatible",
                    reason=(
                        f"Overlay was authored in appearance state {op.appearance_state_id!r} "
                        f"but character {op.subject_character_id!r} is now in state "
                        f"{subject.appearance_state_id!r}; dropping to avoid misapplication."
                    ),
                    operation=op,
                ))
                continue
            setattr(subject, op.field, value)
            reapplied.append(op)
            continue

        # Panel-scoped op. A location-sensitive correction revalidates against
        # the panel's active location state.
        if op.location_state_id is not None:
            current_location_state = getattr(prompt, "location_state_id", None)
            if current_location_state != op.location_state_id:
                warnings.append(OverlayWarning(
                    code="location_state_incompatible",
                    reason=(
                        f"Overlay was authored in location state {op.location_state_id!r} "
                        f"but the panel is now in location state {current_location_state!r}."
                    ),
                    operation=op,
                ))
                continue
        setattr(prompt, op.field, value)
        reapplied.append(op)

    prompt.user_overlays = reapplied
    return warnings


def _find_subject_for_overlay(prompt: ImagePrompt, op: PromptOverlayOp):
    """Locate the subject an op targets, by character id (never by index)."""
    target_id = (op.subject_character_id or "").strip()
    if not target_id:
        return None
    for subject in getattr(prompt, "subjects", []) or []:
        if (getattr(subject, "character_id", None) or "") == target_id:
            return subject
    return None


def _subject_state_compatible(subject, op: PromptOverlayOp) -> bool:
    """True when an op authored in ``op.appearance_state_id`` can apply to ``subject``.

    A state-neutral op (``appearance_state_id`` is None) applies whenever the
    subject is present. A state-specific op applies only when the subject's
    active state matches the op's authored state. This is what drops a
    "uses both hands" correction when the character enters a no-hands state.
    """
    if op.appearance_state_id is None:
        return True
    return (
        getattr(subject, "appearance_state_id", None) == op.appearance_state_id
    )


def prompt_is_current(
    prompt: ImagePrompt,
    panel: PlannedPanel,
    *,
    story_bible: StoryBible | None = None,
    project_dir: Path | None = None,
    prev_panel: PlannedPanel | None = None,
    config: Config | None = None,
) -> bool:
    """True when a stored ImagePrompt still matches its canonical source.

    Slice 03: currency is content-based, not ID/version-based. A prompt is
    current when (a) it is on the current prompt schema version, (b) it is
    still bound to ``panel``, and (c) its recorded ``source_sha256`` equals the
    source hash of a fresh build from the current Story Bible + PlannedPanel.

    When ``story_bible``/``project_dir``/``config`` are supplied, the content
    check recomputes the candidate hash; otherwise the call falls back to the
    legacy schema/panel-id identity check (used by tests that build prompts in
    isolation without a Story Bible). A mismatch on the recorded hash means an
    upstream change altered the canonical content and the prompt must be rebuilt.
    """
    if getattr(prompt, "prompt_version", 1) < IMAGE_PROMPT_VERSION:
        return False
    if getattr(prompt, "planned_panel_id", None) != panel.panel_id:
        return False
    if story_bible is None or project_dir is None or config is None:
        return True
    candidate = _source_inputs_hash(
        config, project_dir, panel, story_bible, prev_panel
    )
    return (getattr(prompt, "source_sha256", None) or "") == candidate


def ensure_current_panel_prompt(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None = None,
) -> ImagePrompt:
    """Return the panel's stored ImagePrompt, rebuilding (and persisting) it
    when stale.

    Single owner of the "is this prompt up to date?" decision — the direct
    stage, the draw stage's pre-pass, and single-panel regeneration all call
    this instead of re-implementing the check.

    Slice 03: a rebuild recompiles canonical source, then reapplies every valid
    user overlay, then invalidates the derived visual brief/layout, then
    persists the new lineage. A stale prompt whose source hash changed is
    rebuilt; a current prompt is returned as-is. Overlay warnings (a dropped
    correction for a removed subject or an incompatible state) are logged.
    """
    from novel_to_comic.layout_planning import prompt_path_for_panel

    prompt_path = prompt_path_for_panel(project_dir, panel)
    existing: ImagePrompt | None = None
    if prompt_path.exists():
        try:
            existing = ImagePrompt.model_validate_json(prompt_path.read_text())
        except Exception:
            existing = None

    if existing is not None and prompt_is_current(
        existing,
        panel,
        story_bible=story_bible,
        project_dir=project_dir,
        prev_panel=prev_panel,
        config=config,
    ):
        return existing

    fresh = build_planned_panel_prompt_spec(config, project_dir, panel, story_bible, prev_panel)
    fresh.source_sha256 = compute_source_sha256(
        config, project_dir, panel, story_bible, prev_panel
    )
    if existing is not None and existing.user_overlays:
        warnings = reapply_overlays(fresh, existing.user_overlays)
        for warning in warnings:
            logger.warning(
                "Dropped stale overlay for panel %s/%s: code=%s reason=%s",
                panel.scene_id, panel.panel_number, warning.code, warning.reason,
            )
        fresh.full_prompt = rerender_prompt_body(fresh)
        fresh.distilled_prompt = generate_distilled_prompt(fresh)
        fresh.visual_brief = None
        fresh.layout = None
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(fresh.model_dump_json(indent=2))
    return fresh


def rerender_prompt_body(prompt: ImagePrompt) -> str:
    """Re-render full_prompt from the stored prompt fields after an edit.

    Handles the narration-caption constraint note idempotently so the note
    never appears twice regardless of whether a previous build already embedded
    it in ``prompt.constraints``.
    """
    constraints = _apply_narration_constraint(
        getattr(prompt, "constraints", None),
        getattr(prompt, "has_narration_caption", False),
    )
    return _render_panel_prompt_body_parts(
        subjects=getattr(prompt, "subjects", []) or [],
        composition=getattr(prompt, "composition", None),
        setting=getattr(prompt, "setting", None),
        lighting=getattr(prompt, "lighting", None),
        mood=getattr(prompt, "mood", None),
        key_objects=getattr(prompt, "key_objects", []) or [],
        visual_requirements=getattr(prompt, "visual_requirements", []) or [],
        props=getattr(prompt, "props", []) or [],
        constraints=constraints,
    )


# ── LLM visual-brief pass ────────────────────────────────────────────────────
#
# The structured ImagePrompt is the source of truth, but image models respond
# best to flowing, art-direction prose — not labeled key:value clauses. This
# pass rewrites the structured spec into that prose with a cheap text model.
# On any failure the prompt simply keeps visual_brief=None and generation
# falls back to the deterministic distilled prompt.

VISUAL_BRIEF_SYSTEM_PROMPT = (
    "You write the final prompt sent to an image-generation model (Reve, GPT Image, "
    "Gemini) for one comic-book panel. Rewrite the structured panel spec you receive "
    "as a single flowing visual brief of 90-160 words: vivid, concrete, present-tense "
    "prose, the way a film director describes one frozen frame.\n"
    "\n"
    "Rules:\n"
    "- Open with the framing (shot type and camera angle), then the subjects.\n"
    "- Introduce each character by name with their full physical description (age, "
    "build, hair, face, wardrobe) immediately, BEFORE their action, so appearance "
    "binds to the right character.\n"
    "- Preserve EVERY concrete visual fact in the spec: appearance, wardrobe, action, "
    "expression, position, props, objects, setting, lighting, mood, must-show details, "
    "caption space. Never invent characters, objects, text, or story beats that are "
    "not in the spec, and never drop one.\n"
    "- Exactly one frozen instant: no sequences, no before/after, no motion trails.\n"
    "- Give light its own concrete sentence: direction, color, quality, and where the "
    "shadows fall.\n"
    "- State spatial relationships explicitly: where each subject and object sits "
    "relative to the others and to the frame.\n"
    "- Respect every hard constraint in the spec (character count, no lettering, "
    "single instant) without quoting it as a rule — express it through the description.\n"
    "- Plain declarative prose only. No headings, labels, bullet points, markdown, "
    "quotation marks, or meta-commentary. Do not mention the spec or that this is a "
    "prompt.\n"
    "- Do not describe art style, medium, or rendering technique — the style template "
    "is appended separately and must not be contradicted.\n"
    "\n"
    "Output only the brief text."
)

_BRIEF_LABEL_RE = re.compile(r"^(?:visual\s+brief|brief|prompt)\s*[:\-]\s*", re.IGNORECASE)


def normalize_prose_brief(raw: str) -> str | None:
    """Clean LLM prose output into a single paragraph, or reject it.

    Shared by the panel visual-brief pass and the S2 style-sample brief.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body_lines = lines[1:-1] if len(lines) >= 3 and lines[-1].strip().startswith("```") else lines[1:]
        text = "\n".join(body_lines).strip()
    if text.startswith(("-", "*", "#", ">")):
        return None
    text = re.sub(r"\s+", " ", text).strip().strip('"').strip()
    text = _BRIEF_LABEL_RE.sub("", text).strip()
    if len(text) < 40 or len(text) > 2000:
        return None
    return text


async def generate_visual_brief(config: Config, prompt: ImagePrompt) -> str | None:
    """One LLM call: structured panel spec → prose visual brief.

    Returns None (never raises) when the spec is empty, the call fails, or the
    output fails validation — callers fall back to the distilled prompt.
    """
    spec = visual_brief_source_spec(prompt)
    if not spec.strip():
        return None
    from novel_to_comic.clients import text

    try:
        result = await text.generate_text(
            config=config,
            model=config.effective_prompt_model(),
            system_prompt=VISUAL_BRIEF_SYSTEM_PROMPT,
            user_content=spec,
            temperature=0.4,
            max_output_tokens=4096,
            feature="prompt.visual_brief",
        )
    except Exception:
        logger.warning(
            "Visual brief generation failed for panel %s/%s; falling back to distilled prompt",
            getattr(prompt, "scene_id", "?"),
            getattr(prompt, "panel_number", "?"),
            exc_info=True,
        )
        return None
    brief = normalize_prose_brief(result.value)
    if brief is None:
        raw = result.value or ""
        logger.warning(
            "Visual brief output rejected for panel %s/%s (len=%d, starts=%r); "
            "falling back to distilled prompt",
            getattr(prompt, "scene_id", "?"),
            getattr(prompt, "panel_number", "?"),
            len(raw.strip()),
            raw.strip()[:60],
        )
    return brief


async def ensure_visual_brief(config: Config, prompt: ImagePrompt) -> ImagePrompt:
    """Return prompt with visual_brief populated when possible.

    Returns the same object when the brief already exists, the pass is
    disabled, or generation fails — callers can use identity to decide
    whether to persist.
    """
    if not getattr(config, "visual_brief_enabled", True):
        return prompt
    if (getattr(prompt, "visual_brief", None) or "").strip():
        return prompt
    brief = await generate_visual_brief(config, prompt)
    if not brief:
        return prompt
    updated = prompt.model_copy(deep=True)
    updated.visual_brief = brief
    return updated


# ── LLM layout pass (Reve v2 regional prompting) ────────────────────────────
#
# Decomposes the structured panel spec into a labelled, bounded region map for
# Reve v2. Subject regions carry a reference_key (character id) so the
# provider wire compiler can bind that character's reference image to the
# region. Native region types and parent links let Reve spend detail budget on
# faces, hands, and important props instead of treating every box as a flat
# background rectangle. On any failure the prompt keeps layout=None and
# generation falls back to the flat visual brief.

LAYOUT_SYSTEM_PROMPT = (
    "You are a comic-panel layout director. Decompose the panel spec you receive "
    "into a flat list of rectangular regions for a layout-aware image model.\n"
    "\n"
    "Coordinates: every bbox is {x0, y0, x1, y1} with values in [0, 1], top-left "
    "origin, absolute to the full canvas. x0 < x1 and y0 < y1.\n"
    "\n"
    "Rules:\n"
    "- Output 2-10 regions. Big elements first (background/setting, then each "
    "character), detail regions after.\n"
    "- Use region_type: coarse_detail for the setting and full characters; "
    "medium_detail for a major prop or limb; fine_detail for a small key "
    "object; face for a visible face; hand for a hand that carries important "
    "action or an object. Never use the text region type: lettering is added "
    "later by compose, not rendered into the panel image.\n"
    "- Detail regions may be nested under a containing region using parent; "
    "their boxes must lie inside the parent's box.\n"
    "- Every region label must be unique, short, and snake_case.\n"
    "- Each region prompt describes ONLY what is inside that box, in concrete "
    "visual terms. Never mention other regions, the spec, or art style.\n"
    "- For each character in the spec, emit exactly one region covering their "
    "full body placement, set region_type to coarse_detail, and set "
    "reference_key to that character's id from the spec. Regions without a "
    "listed id use reference_key: null.\n"
    "- Respect stated positions (left/right/foreground/background) and the "
    "panel's aspect ratio when placing boxes.\n"
    "- Background/setting regions should cover the canvas areas not dominated by "
    "subjects; boxes may overlap.\n"
    "- If the spec reserves quiet space for a narration caption, keep that zone "
    "free of detail regions.\n"
    "\n"
    'Output JSON only: {"prompt": "<one-sentence overall scene summary>", '
    '"regions": [{"label": "...", "prompt": "...", '
    '"bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}, '
    '"reference_key": "<character id or null>", '
    '"parent": "<containing label or null>", '
    '"region_type": "<coarse_detail|medium_detail|fine_detail|face|hand>"}]}'
)

_LAYOUT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "prompt": {"type": ["string", "null"]},
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "prompt": {"type": "string"},
                    "bbox": {
                        "type": "object",
                        "properties": {
                            "x0": {"type": "number"},
                            "y0": {"type": "number"},
                            "x1": {"type": "number"},
                            "y1": {"type": "number"},
                        },
                        "required": ["x0", "y0", "x1", "y1"],
                    },
                    "reference_key": {"type": ["string", "null"]},
                    "parent": {"type": ["string", "null"]},
                    "region_type": {
                        "type": ["string", "null"],
                        "enum": [
                            "coarse_detail",
                            "medium_detail",
                            "fine_detail",
                            "hand",
                            "face",
                            None,
                        ],
                    },
                },
                "required": ["label", "prompt", "bbox"],
            },
        },
    },
    "required": ["regions"],
}


def _layout_source_spec(prompt: ImagePrompt) -> str:
    """Spec text for the layout pass: brief/spec plus binding keys and frame shape."""
    spec = visual_brief_source_spec(prompt)
    if not spec.strip():
        return ""
    lines = [spec]
    character_ids = [
        f"- {subject.character_id}: {subject.name}"
        for subject in getattr(prompt, "subjects", []) or []
        if (getattr(subject, "character_id", None) or "").strip()
    ]
    if character_ids:
        lines.append("Character ids for reference_key:\n" + "\n".join(character_ids))
    brief = (getattr(prompt, "visual_brief", None) or "").strip()
    if brief:
        lines.append(f"Visual brief (final composition intent): {brief}")
    width = getattr(prompt, "generation_width", None) or prompt.width
    height = getattr(prompt, "generation_height", None) or prompt.height
    if width and height:
        orientation = "landscape" if width > height else "portrait" if height > width else "square"
        lines.append(f"Canvas: {width}x{height} ({orientation})")
    return "\n\n".join(lines)


def layout_pass_applies(config: Config, prompt: ImagePrompt | None = None) -> bool:
    """True when the layout pass should run for this config (and prompt)."""
    from novel_to_comic.config import is_reve_model

    if not getattr(config, "layout_prompts_enabled", True):
        return False
    if not is_reve_model(config.effective_image_model()):
        return False
    if prompt is not None and getattr(prompt, "layout", None) is not None:
        return False
    return True


async def generate_layout(config: Config, prompt: ImagePrompt) -> PromptLayout | None:
    """One LLM call: structured panel spec → flat region layout.

    Returns None (never raises) when the spec is empty, the call fails, or the
    output sanitizes down to fewer than two regions — callers fall back to
    flat prompting.
    """
    spec = _layout_source_spec(prompt)
    if not spec.strip():
        return None
    from novel_to_comic.ai.client import generate_structured_object

    try:
        result = await generate_structured_object(
            config=config,
            model=config.effective_prompt_model(),
            system_prompt=LAYOUT_SYSTEM_PROMPT,
            user_content=spec,
            temperature=0.3,
            max_output_tokens=4096,
            json_schema=_LAYOUT_JSON_SCHEMA,
            feature="prompt.layout",
        )
        layout = PromptLayout.model_validate(result.value).sanitized()
    except Exception:
        logger.warning(
            "Layout generation failed for panel %s/%s; falling back to flat prompt",
            getattr(prompt, "scene_id", "?"),
            getattr(prompt, "panel_number", "?"),
            exc_info=True,
        )
        return None
    if len(layout.regions) < 2:
        logger.warning(
            "Layout output rejected for panel %s/%s (%d usable regions); "
            "falling back to flat prompt",
            getattr(prompt, "scene_id", "?"),
            getattr(prompt, "panel_number", "?"),
            len(layout.regions),
        )
        return None
    return layout


async def ensure_layout(config: Config, prompt: ImagePrompt) -> ImagePrompt:
    """Return prompt with layout populated when the layout pass applies.

    Returns the same object when a layout already exists, the pass is disabled,
    the image model is not layout-aware, or generation fails — callers can use
    identity to decide whether to persist.
    """
    if not layout_pass_applies(config, prompt):
        return prompt
    layout = await generate_layout(config, prompt)
    if layout is None:
        return prompt
    width = getattr(prompt, "generation_width", None) or prompt.width
    height = getattr(prompt, "generation_height", None) or prompt.height
    frame_width, frame_height = dimensions_for_reve_layout(width, height)
    layout = layout.model_copy(update={"width": frame_width, "height": frame_height})
    updated = prompt.model_copy(deep=True)
    updated.layout = layout
    return updated


__all__ = [
    "IMAGE_PROMPT_VERSION",
    "LAYOUT_SYSTEM_PROMPT",
    "VISUAL_BRIEF_SYSTEM_PROMPT",
    "assemble_panel_prompt",
    "compute_source_sha256",
    "ensure_current_panel_prompt",
    "ensure_distilled_prompt",
    "ensure_layout",
    "ensure_visual_brief",
    "generate_layout",
    "generate_visual_brief",
    "layout_pass_applies",
    "normalize_prose_brief",
    "prompt_is_current",
    "reapply_overlays",
    "rerender_prompt_body",
]
