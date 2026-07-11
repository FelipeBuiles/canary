"""Canonical prompt-body projection (Slice 02).

Renders a deterministic prompt-body projection from the owned sections of an
``ImagePrompt``:

- Protected verbatim anchors (character identity on subjects, location/prop
  anchors) — emitted unchanged.
- Editable scene direction (composition, setting, lighting, mood, key objects,
  visual requirements) — owned by the structured fields.
- Generated system constraints (character count, one body per character, single
  frozen instant, no lettering, crop policy, appearance locks, unified canvas)
  — generated from typed fields, never stored in the editable ``constraints``.
- User constraint addenda — the only editable part of the constraint surface.

This is the **canonical projection**, not the final provider-bound prompt.
Slice 05 will combine it with a finalized reference plan into the exact
provider-bound request. It does not contain the finalized reference selection
or role instructions.

The system/user constraint split means manual and instructed edits can change
scene direction and user addenda but can never remove a system constraint: it
is regenerated from typed fields on every render.
"""

from __future__ import annotations

from novel_to_comic.models.prompt import ImagePrompt, PromptAnchor, PromptSubject
from novel_to_comic.text_utils import clean as _clean

# Generated system-constraint lines. These are typed invariants, not editable
# prose — the canonical projection emits them from the ImagePrompt's typed
# fields on every render.
_NARRATION_NOTE = (
    "narration caption will be lettered in post-production only; "
    "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
)
_UNIFIED_CANVAS = (
    "One unified scene filling the entire canvas — no sub-panels, gutters, "
    "internal borders, page layouts, or split-screen compositions."
)

# Character-count / figure / instant / no-lettering labels follow the prompting
# module's i18n label table. The canonical projection reuses them so the
# constraint vocabulary stays in one place.
from novel_to_comic.prompting import _PROMPT_LABELS  # noqa: E402


def _labels(prompt: ImagePrompt) -> dict[str, str]:
    # Language is not carried on ImagePrompt today; the canonical projection
    # uses English labels (the default). Slice 06 (prompt hygiene) may revisit.
    return _PROMPT_LABELS["en"]


def _character_anchor_lines(subjects: list[PromptSubject]) -> list[str]:
    """Emit each subject's verbatim identity anchor.

    The identity is immutable source material — never shortened, filtered, or
    paraphrased here.
    """
    lines: list[str] = []
    for subject in subjects:
        identity = (subject.identity or "").strip()
        if not identity:
            continue
        lines.append(f"{subject.name}: {identity}")
    return lines


def _location_prop_anchor_lines(anchors: list[PromptAnchor]) -> list[str]:
    """Emit location and prop anchors verbatim."""
    lines: list[str] = []
    for anchor in anchors:
        text = (anchor.text or "").strip()
        if not text:
            continue
        lines.append(f"{anchor.name}: {text}")
    return lines


def _appearance_lock_clauses(prompt: ImagePrompt) -> list[str]:
    """Hard-constraint clauses for entities in a non-base, visually-significant
    appearance state (characters and the location)."""
    clauses: list[str] = []
    for subject in getattr(prompt, "subjects", []) or []:
        if not getattr(subject, "appearance_locked", False):
            continue
        name = subject.name
        clause = (
            f"{name} is shown in a fixed altered appearance — render {name} EXACTLY "
            f"as described and as the reference image; do not restore {name}'s default "
            f"look or add features not shown"
        )
        guard = (getattr(subject, "appearance_guard", None) or "").strip().rstrip(".")
        if guard:
            clause += f" ({guard})"
        clauses.append(clause)

    # Location appearance lock (significant location state). The location anchor
    # already carries the per-state tags; the lock clause forbids reverting to
    # the base location.
    loc_anchors = [a for a in (getattr(prompt, "anchors", []) or []) if a.kind == "location"]
    if prompt.location_state_id:
        for loc in loc_anchors:
            if loc.appearance_state_id:
                name = loc.name
                clauses.append(
                    f"{name} is shown in a fixed altered state — render {name} EXACTLY "
                    f"as described; do not revert {name} to its default appearance"
                )
    return clauses


def generate_system_constraints(prompt: ImagePrompt) -> list[str]:
    """Generate the system-constraint lines from typed fields.

    These are non-editable invariants: character count, one body per character,
    single frozen instant, no lettering, crop policy, appearance locks, unified
    canvas. Manual and instructed edits cannot remove them because they are
    regenerated on every render — they are never stored in ``constraints``.
    """
    labels = _labels(prompt)
    character_count = len(getattr(prompt, "subjects", []) or [])
    character_label = labels["character"] if character_count == 1 else labels["characters"]
    lines: list[str] = [
        f"exactly {character_count} {character_label}",
        labels["one_body"],
        labels["single_instant"],
        labels["no_lettering"],
    ]
    if getattr(prompt, "has_narration_caption", False):
        lines.append(_NARRATION_NOTE)
    crop_policy = getattr(prompt, "crop_policy", None)
    if crop_policy:
        lines.append(f"crop policy: {crop_policy}")
    lines.extend(_appearance_lock_clauses(prompt))
    lines.append(_UNIFIED_CANVAS)
    return lines


def render_canonical_body(prompt: ImagePrompt) -> str:
    """Render the deterministic canonical prompt-body projection.

    Combines the owned sections into a single semicolon- and period-delimited
    string:

    1. Protected anchors (character identity + location/prop anchors) verbatim.
    2. Scene direction (composition, setting, lighting, mood, props/objects,
       visual requirements, continuity).
    3. System constraints (generated from typed fields).
    4. User constraint addenda.

    This is NOT the final provider-bound prompt — it lacks the finalized
    reference selection and role instructions (Slice 05).
    """
    labels = _labels(prompt)
    sentences: list[str] = []

    # ── Protected anchors (verbatim) ──────────────────────────────────────
    subjects = getattr(prompt, "subjects", []) or []
    char_lines = _character_anchor_lines(subjects)
    anchors = getattr(prompt, "anchors", []) or []
    loc_prop_lines = _location_prop_anchor_lines(anchors)
    anchor_lines = char_lines + loc_prop_lines
    if anchor_lines:
        sentences.append("; ".join(anchor_lines))

    # ── Scene direction (editable) ────────────────────────────────────────
    composition = _clean(getattr(prompt, "composition", None))
    if composition:
        sentences.append(f"{labels['composition']}: {composition}")

    setting = _clean(getattr(prompt, "setting", None))
    if setting:
        sentences.append(f"{labels['setting']}: {setting}")

    lighting = _clean(getattr(prompt, "lighting", None))
    if lighting:
        sentences.append(f"{labels['lighting']}: {lighting}")

    mood = _clean(getattr(prompt, "mood", None))
    if mood:
        sentences.append(f"{labels['mood']}: {mood}")

    props = getattr(prompt, "props", []) or []
    if props:
        sentences.append(f"{labels['key_props']}: {'; '.join(_clean(p) for p in props if _clean(p))}")

    key_objects = [_clean(v) for v in (getattr(prompt, "key_objects", []) or []) if _clean(v)]
    if key_objects:
        sentences.append(f"{labels['key_objects']}: {'; '.join(key_objects)}")

    requirements = [_clean(v) for v in (getattr(prompt, "visual_requirements", []) or []) if _clean(v)]
    if requirements:
        sentences.append(f"{labels['must_show']}: {'; '.join(requirements)}")

    continuity = _clean(getattr(prompt, "continuity_note", None))
    if continuity:
        sentences.append(f"Continuity: {continuity}")

    # ── System constraints (generated, non-editable) ──────────────────────
    system_lines = generate_system_constraints(prompt)
    if system_lines:
        sentences.append("; ".join(system_lines))

    # ── User constraint addenda (editable) ────────────────────────────────
    user_constraints = _clean(getattr(prompt, "constraints", None))
    if user_constraints:
        sentences.append(user_constraints)

    body = ". ".join(s.rstrip(" .") for s in sentences if s).strip()
    return f"{body}." if body else ""


__all__ = [
    "generate_system_constraints",
    "render_canonical_body",
]
