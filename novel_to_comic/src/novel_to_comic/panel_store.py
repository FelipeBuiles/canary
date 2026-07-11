"""Panel store — owns panel record read/write across its lifecycle (s5 → s9).

Routes and stages should call these instead of reaching into ``artifacts`` and
then manually re-rendering / re-distilling.  Centralising the operations here
means the "read → validate → patch → re-render → write" pipeline has one owner
and callers can't omit steps (e.g. forgetting to re-derive ``full_prompt`` after
editing prompt fields).

Slice 01 — derived-state ownership
-----------------------------------
A manual edit arrives as an *explicit patch* of authoritative structured fields
(``apply_prompt_patch``).  The server owns derived-field invalidation so a
corrected draft can never regenerate an old scene from a stale visual brief or
layout:

- a *semantic* change (composition, setting, lighting, mood, subjects,
  constraints, props, ...) clears ``visual_brief`` and ``layout``;
- a *layout-only* change preserves the supplied layout and the visual brief;
- any *accepted instructed* semantic change clears layout as well as both
  prompt bodies (handled in ``prompt_instructions``).

Client attempts to set derived fields (``visual_brief``, ``distilled_prompt``,
``full_prompt``), reference data (``reference_image_paths``), identity anchors
(``subjects[].identity``), or system constraints are rejected by the patch
contract.  Only the authoritative field set below is accepted.
"""

from pathlib import Path
from typing import Any

from novel_to_comic import artifacts
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt, PromptOverlayOp, PromptSubject
from novel_to_comic.prompt_assembly import rerender_prompt_body
from novel_to_comic.prompting import generate_distilled_prompt

# ── Authoritative editable field set ─────────────────────────────────────────
#
# These are the only prompt fields a manual edit may set.  Anchors, reference
# paths, system constraints, visual briefs, distilled prompts, and rendered
# prompt strings are excluded — they are derived or protected.

# Simple scalar/leaf authoritative fields (string-or-list-of-str values).
AUTHORITATIVE_PROMPT_FIELDS: frozenset[str] = frozenset(
    {
        "composition",
        "setting",
        "lighting",
        "mood",
        "constraints",
        "continuity_note",
        "props",
        "key_objects",
        "visual_requirements",
    }
)

# Fields whose mutation changes the *semantic content* of the generated scene,
# invalidating the LLM-composed visual brief and the region layout.  ``layout``
# is intentionally absent — a layout-only edit must preserve derived state.
_SEMANTIC_FIELD_KEYS: frozenset[str] = AUTHORITATIVE_PROMPT_FIELDS | {"subjects"}

# Fields a client may never set through the patch contract.  Setting any of
# these raises ``ValueError`` so the API surface returns 400 rather than
# silently trusting attacker-controlled derived/reference data.
APPLY_PROMPT_PATCH_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "full_prompt",
        "distilled_prompt",
        "visual_brief",
        "reference_image_paths",
        "style",
        "prompt_version",
        "planned_panel_id",
        "scene_id",
        "panel_number",
        "width",
        "height",
        "steps",
        "has_narration_caption",
        "narration_mode",
        "preferred_caption_zone",
        "location_id",
        "location_state_id",
        "anchors",
        "generation_mode",
        "shape_intent",
        "generation_aspect_ratio",
        "generation_width",
        "generation_height",
        "generation_shape",
        "generation_aspect_source",
        "crop_policy",
        "transition_in",
        "transition_out",
    }
)


def apply_prompt_patch(prompt: ImagePrompt, patch: dict[str, Any]) -> ImagePrompt:
    """Apply an authoritative field patch and invalidate derived state.

    ``patch`` is an explicit ``{field: value}`` mapping of only the fields the
    client changed.  Forbidden keys (derived fields, reference paths, identity
    anchors, system-immutables) raise ``ValueError``.

    Invalidation rules (centralized here, the single owner):

    - any semantic field change (incl. ``subjects``) clears ``visual_brief``
      and ``layout`` so a corrected draft cannot regenerate the old scene;
    - a ``layout``-only change preserves the supplied layout and leaves the
      visual brief intact.

    ``full_prompt`` is always re-derived from the structured fields;
    ``distilled_prompt`` is regenerated deterministically.  The visual brief is
    left ``None`` when invalidated — callers (draw/rerender) hydrate it through
    the shared ``ensure_visual_brief`` path.

    Slice 03: semantic edits are also recorded as overlay ops on
    ``user_overlays`` (keyed to entity id + appearance/location state), so a
    later canonical rebuild reappies the correction instead of silently dropping
    the user's intent.

    Returns a new ``ImagePrompt``; the input is not mutated.
    """
    unknown = set(patch) - AUTHORITATIVE_PROMPT_FIELDS - {"subjects", "layout"}
    forbidden = set(patch) & APPLY_PROMPT_PATCH_FORBIDDEN_KEYS
    if forbidden:
        raise ValueError(
            "Patch rejects derived/protected fields: " + ", ".join(sorted(forbidden))
        )
    if unknown:
        raise ValueError("Unknown prompt patch fields: " + ", ".join(sorted(unknown)))

    updated = prompt.model_copy(deep=True)

    semantic_changed = bool(set(patch) & _SEMANTIC_FIELD_KEYS)

    new_overlays: list[PromptOverlayOp] = []
    for key, value in patch.items():
        if key == "subjects":
            new_subjects = _coerce_subjects(value)
            new_overlays.extend(_subject_overlay_ops(prompt.subjects, new_subjects))
            updated.subjects = new_subjects
        elif key == "layout":
            updated.layout = value
        else:
            setattr(updated, key, value)
            new_overlays.append(PromptOverlayOp(
                field=key,  # type: ignore[arg-type]
                value=str(value),
                location_state_id=getattr(prompt, "location_state_id", None),
            ))

    # Centralized derived-field invalidation.
    if semantic_changed:
        updated.visual_brief = None
        updated.layout = None
    # A layout-only edit preserves the supplied layout and the visual brief.

    updated.full_prompt = rerender_prompt_body(updated)
    updated.distilled_prompt = generate_distilled_prompt(updated)
    if new_overlays:
        updated.user_overlays = _merge_overlays(updated.user_overlays, new_overlays)
    return updated


def _subject_overlay_ops(
    original: list[PromptSubject], patched: list[PromptSubject]
) -> list[PromptOverlayOp]:
    """Build overlay ops from a subject patch, keyed to character id + state.

    Matches patched subjects to originals by index (the patch replaces the whole
    subject list in order) so each changed scene-direction field is recorded as
    an overlay bound to that character's id and active appearance state. This is
    what lets a rebuild reapply a per-character correction to the right subject
    instead of a positional index.
    """
    ops: list[PromptOverlayOp] = []
    subject_fields = ("action", "expression", "position")
    for index, new_subject in enumerate(patched):
        if index >= len(original):
            continue
        old = original[index]
        for field in subject_fields:
            new_value = getattr(new_subject, field, "") or ""
            old_value = getattr(old, field, "") or ""
            if new_value != old_value and new_value:
                ops.append(PromptOverlayOp(
                    field=field,  # type: ignore[arg-type]
                    value=new_value,
                    subject_character_id=getattr(old, "character_id", None),
                    appearance_state_id=getattr(old, "appearance_state_id", None),
                ))
    return ops


def _merge_overlays(
    existing: list[PromptOverlayOp], additions: list[PromptOverlayOp]
) -> list[PromptOverlayOp]:
    """Merge new overlay ops onto the existing list, deduplicating by key.

    An op's key is (field, subject_character_id, appearance_state_id,
    location_state_id): a new correction for the same field+entity+state
    supersedes the older one. Different fields on the same entity coexist.
    """
    merged: list[PromptOverlayOp] = []
    keys: set[tuple] = set()

    def _key(op: PromptOverlayOp) -> tuple:
        return (op.field, op.subject_character_id, op.appearance_state_id, op.location_state_id)

    for op in additions:
        merged.append(op)
        keys.add(_key(op))
    for op in existing or []:
        if _key(op) in keys:
            continue
        merged.append(op)
        keys.add(_key(op))
    return merged


def _coerce_subjects(value: Any) -> list[PromptSubject]:
    """Coerce a patch ``subjects`` value into validated PromptSubject models.

    Rejects any attempt to mutate ``identity``/``appearance_locked``/``appearance_guard``
    — those are protected identity anchors (canonical source material), not
    editable scene direction.
    """
    if not isinstance(value, list):
        raise ValueError("subjects patch must be a list")
    forbidden_subject_keys = {
        "identity",
        "appearance_locked",
        "appearance_guard",
        "appearance_state_id",
        "character_id",
        "name",
    }
    out: list[PromptSubject] = []
    for index, item in enumerate(value):
        if isinstance(item, PromptSubject):
            # Internal callers pass validated models; the wire path (dicts) is
            # where untrusted identity/anchor mutations are rejected below.
            out.append(item.model_copy(deep=True))
            continue
        if not isinstance(item, dict):
            raise ValueError(f"subjects[{index}] must be an object")
        forbidden_subject = set(item) & forbidden_subject_keys
        if forbidden_subject:
            raise ValueError(
                "subjects patch rejects identity/anchor fields: "
                + ", ".join(sorted(forbidden_subject))
            )
        out.append(PromptSubject.model_validate(item))
    return out


def load_breakdown(project_dir: Path, scene_id: str, panel_number: int) -> PanelBreakdown | None:
    """Return the PanelBreakdown for a panel, or None if the file doesn't exist."""
    path = artifacts.panel_breakdown_path(project_dir, scene_id, panel_number)
    if not path.exists():
        return None
    return PanelBreakdown.model_validate_json(path.read_text())


def save_breakdown(
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    data: dict,
) -> PanelBreakdown:
    """Validate ``data`` as a PanelBreakdown and persist it.

    Returns the validated model so callers can use the canonical representation.
    Raises ``ValueError`` if ``data`` fails validation.
    """
    updated = PanelBreakdown.model_validate(data)
    artifacts.write_panel_breakdown(project_dir, scene_id, panel_number, updated)
    return updated


def load_prompt(project_dir: Path, scene_id: str, panel_number: int) -> ImagePrompt | None:
    """Return the ImagePrompt for a panel, or None if the file doesn't exist."""
    path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not path.exists():
        return None
    return ImagePrompt.model_validate_json(path.read_text())


def save_prompt(
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    data: dict,
) -> ImagePrompt:
    """Validate ``data`` as an ImagePrompt, re-derive rendered fields, and persist.

    Re-derives ``full_prompt`` from the structured fields and regenerates
    ``distilled_prompt`` so callers can't accidentally leave them stale after
    editing prompt fields.

    Returns the updated model.  Raises ``ValueError`` if ``data`` fails validation.
    """
    updated = ImagePrompt.model_validate(data)
    updated.full_prompt = rerender_prompt_body(updated)
    updated.distilled_prompt = generate_distilled_prompt(updated)
    artifacts.write_panel_prompt(project_dir, scene_id, panel_number, updated)
    return updated
