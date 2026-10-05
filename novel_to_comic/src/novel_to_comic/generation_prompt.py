"""Canonical prompt-body projection (Slice 02).

Renders a deterministic prompt-body projection from the owned sections of an
``GenerationPromptInput``:

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

from novel_to_comic import reference_forms
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.text_utils import clean as _clean
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_CONSTRAINTS

# Generated system-constraint lines. These are typed invariants, not editable
# prose — the canonical projection emits them from typed generation input
# fields on every render.
_NARRATION_NOTE = (
    "narration caption will be lettered in post-production only; "
    "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
)
_UNIFIED_CANVAS = (
    "One unified scene filling the entire canvas — no sub-panels, gutters, "
    "internal borders, page layouts, or split-screen compositions."
)

_FACIAL_QUALITY = (
    "Preserve the active anchor's age, species, anatomy, and facial identity in the "
    "selected rendering style; avoid accidental distortion, not intentional stylization",
)

_BODY_PROPORTION_QUALITY = (
    "Use the anatomy, proportions, and silhouette specified by the active anchor; "
    "explicit changed anatomy and age override canonical-parent proportions",
)

_SHARED_ARTISTIC_HAND = (
    "Render every character with one shared artistic hand: identical contour language, "
    "line weight, facial modeling, wash behavior, palette, edge treatment, shadow density, "
    "and degree of simplification",
    "Character references define identity, anatomy, and wardrobe only; do not inherit "
    "their medium, mark-making, palette, lighting, paper texture, or rendering density",
)


_ENGLISH_LABELS = {
    "composition": "Composition",
    "setting": "Setting",
    "lighting": "Lighting",
    "mood": "Mood",
    "key_props": "Key props",
    "key_objects": "Key objects",
    "must_show": "Must show",
    "expression": "expression",
    "position": "position",
    "wardrobe_override": (
        "current wardrobe (overrides any clothing mentioned above)"
    ),
    "character": "character",
    "characters": "characters",
    "one_body": "one body per listed character",
    "single_instant": "single frozen instant, not a sequence or split-screen",
    "no_lettering": (
        "no text, captions, speech balloons, or lettering anywhere in the image"
    ),
    "style_authority": (
        "Use the selected visual style above as authoritative if later prompt "
        "text conflicts."
    ),
}


def _labels(prompt: GenerationPromptInput) -> dict[str, str]:
    # Language is not carried on generation input today; the canonical projection
    # uses English labels (the default). Slice 06 (prompt hygiene) may revisit.
    return _ENGLISH_LABELS


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


def _appearance_lock_clauses(prompt: GenerationPromptInput) -> list[str]:
    """Hard-constraint clauses for entities in a non-base, visually-significant
    appearance state (characters and the location)."""
    clauses: list[str] = []
    for subject in getattr(prompt, "subjects", []) or []:
        if not getattr(subject, "appearance_locked", False):
            continue
        name = subject.name
        # The changed look is fixed; the reference's pose and framing are not.
        clause = (
            f"{name} is shown in a fixed altered appearance — render the described "
            f"changes to {name}'s body, face, hair and clothing exactly; do not restore "
            f"{name}'s default look or add features not described"
        )
        # Verbatim guards are emitted with their protected entity anchors.
        clauses.append(clause)

    # Location appearance lock (significant location state). The location anchor
    # already carries the per-state tags; the lock clause forbids reverting to
    # the base location.
    loc_anchors = [a for a in (getattr(prompt, "anchors", []) or []) if a.kind == "location"]
    if getattr(prompt, "location_state_id", None):
        for loc in loc_anchors:
            if loc.appearance_state_id:
                name = loc.name
                clauses.append(
                    f"{name} is shown in a fixed altered state — render {name} EXACTLY "
                    f"as described; do not revert {name} to its default appearance"
                )
    return clauses


def generate_system_constraints(
    prompt: GenerationPromptInput,
    *,
    asset_kind: str = "panel",
    has_style_reference: bool = False,
    has_subject_references: bool = False,
) -> list[str]:
    """Generate the system-constraint lines from typed fields.

    These are non-editable invariants: character count, one body per character,
    single frozen instant, no lettering, crop policy, appearance locks, unified
    canvas. Manual and instructed edits cannot remove them because they are
    regenerated on every render — they are never stored in ``constraints``.
    """
    labels = _labels(prompt)
    subjects = list(getattr(prompt, "subjects", []) or [])
    character_count = len(subjects)
    character_label = labels["character"] if character_count == 1 else labels["characters"]
    if asset_kind == "character_ref":
        state_sheet = any(getattr(subject, "appearance_state_id", None) for subject in subjects)
        form = next((getattr(subject, "reference_form", "figure") for subject in subjects), "figure")
        layout = (reference_forms.STATE_LAYOUTS if state_sheet else reference_forms.CANONICAL_LAYOUTS)[form]
        lines = [*layout, labels["no_lettering"]]
        # A character's everyday demeanor is acting, owned by Plan per panel; a
        # canonical sheet that bakes it in makes every panel wear the same face.
        for subject in subjects:
            baseline_affect = (getattr(subject, "baseline_affect", None) or "").strip()
            if baseline_affect and getattr(subject, "appearance_state_id", None):
                lines.append(
                    f"state affect for {subject.name}: {baseline_affect}; render it "
                    "subtly and consistently without escalating its intensity"
                )
        lines.extend(_FACIAL_QUALITY)
        lines.extend(_BODY_PROPORTION_QUALITY)
        # A state reference may intentionally require fever, delirium, or another
        # altered affect. Preserve it, but do not let the model amplify beyond the
        # authored state description.
        if state_sheet:
            lines.append(
                "honor any explicitly authored appearance-state affect, but do not "
                "intensify it beyond the state description"
            )
        else:
            lines.append(reference_forms.PERFORMANCE[form])
    elif asset_kind == "style_sample":
        lines = [
            f"exactly {character_count} distinct listed {character_label}",
            "the listed character may recur across panels but must keep one identity",
            "one coherent complete comic page, not unrelated images or a contact sheet",
        ]
        if subjects:
            lines.extend(_FACIAL_QUALITY)
    else:
        lines = [
            f"exactly {character_count} {character_label}",
            *([labels["one_body"]] if subjects else []),
            labels["single_instant"],
            labels["no_lettering"],
        ]
        if subjects:
            lines.extend(_FACIAL_QUALITY)
    if getattr(prompt, "has_narration_caption", False):
        lines.append(_NARRATION_NOTE)
    crop_policy = getattr(prompt, "crop_policy", None)
    if crop_policy:
        lines.append(f"crop policy: {crop_policy}")
    if prompt.editorial_addendum:
        lines.append(
            "The owner's explicit art direction overrides conflicting appearance and style defaults "
            "throughout this request, including anchors and continuity guards. Preserve unrequested "
            "details and the required reference format. Do not reduce a redesign to a cosmetic variation."
        )
    else:
        lines.extend(_appearance_lock_clauses(prompt))
    if has_style_reference:
        # Reference-specific rendering authority is declared once by the compiler.
        if subjects and has_subject_references:
            lines.extend(_SHARED_ARTISTIC_HAND)
    if asset_kind not in {"character_ref", "style_sample"}:
        lines.append(_UNIFIED_CANVAS)
    # Protected compiler constraints: included in the prompt budget and hash,
    # not appended after freezing or persisted into the selected style itself.
    lines.extend(RENDERING_FIDELITY_CONSTRAINTS)
    return lines


def render_canonical_body(prompt: GenerationPromptInput) -> str:
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
