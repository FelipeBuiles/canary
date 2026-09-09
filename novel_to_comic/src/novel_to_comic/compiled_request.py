"""Slice 05 — the one provider-independent compiled generation request.

``compile_generation_request`` is a PURE function that combines the prepared
canonical Style/Cast generation input with
the already-final :class:`~novel_to_comic.image_references.ReferencePlan`,
the selected style text/spec, the route profile, and explicit generation
controls into one typed, immutable :class:`CompiledGenerationRequest`.

What the compiler owns
----------------------

- Exact ordered semantic prompt sections and the final semantic prompt string.
- Protected anchors emitted byte-for-byte (never transformed by formatting
  helpers).
- One exact semantic instruction per selected reference, compiled by role and
  explicit authority facets — NOT a generic "ignore all backgrounds" guard.
- Effective target geometry (shape + dimensions) projected from the prompt.
- A deterministic ``compiled_request_sha256`` over provider-independent
  execution fields (excluding diagnostics, warnings, and timestamps).

Slice 06 — prompt hygiene, budgets, and geometry truth
-------------------------------------------------------

- Editable/dynamic scene fields are text-sanitized (readable-text cues
  removed) via :mod:`novel_to_comic.prompt_hygiene`. Protected anchors are
  never sanitized; anchor/no-lettering conflicts are emitted as structured
  diagnostics.
- ``visual_requirements`` are normalized, deduplicated against owned facts,
  and capped to the planner's intended 1–4 must-show details.
- Hardcoded medium directives (e.g. unconditional gouache) are stripped;
  medium guidance derives from the active selected style.
- Section-aware budgeting: protected sections (anchors, reference
  instructions, system constraints) are non-truncatable. Lower-priority scene
  prose is compressed first. A request that cannot fit protected material
  fails explicitly — no provider may prefix-slice it later.
- ``GenerationControls`` are verified against the route's supported controls;
  unsupported (phantom) controls raise before transport.
- Native aspect is represented structurally when the route has a dedicated
  aspect parameter.

What the compiler does NOT do
-----------------------------

- No file discovery, LLM call, persistence, or provider call.
- No provider-specific serialization (Reve ``<frame>N</frame>``, signed URLs,
  upload ids). Slice 07 serializes the stored semantic sections.
- No ``actual_provider_model`` field — observed execution identity belongs to
  result provenance after transport.

Active-state authority (global invariant #6): an active appearance/location
state wins over canonical mutable facts. The per-reference instructions make
that explicit: a subject in an identity-only state preserves only compatible
identity facets and ignores named active-state conflicts; a location plate in
an active state defers architecture/landmarks to the active damage/weather/
time anchor.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from novel_to_comic.image_models import ImageModelProfile, ImageRoute
from novel_to_comic.image_references import (
    AuthorityScope,
    ReferenceAsset,
    ReferencePlan,
)
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_geometry import (
    GenerationShape,
    aspect_for_dimensions,
    generation_shape_for_aspect,
)
from novel_to_comic.prompt_hygiene import (
    apply_prompt_budget,
    dedupe_brief_against_continuity,
    detect_anchor_text_conflicts,
    dedupe_visual_requirements,
    sanitize_dynamic_list,
    sanitize_dynamic_text,
    strip_hardcoded_mediums,
)
from novel_to_comic.text_utils import clean as _clean

#: Compiler/schema version. Bumped when the compiled-request shape changes.
COMPILED_REQUEST_SCHEMA_VERSION = 3

AssetKind = Literal[
    "character_ref", "location_plate", "prop_ref", "style_sample", "style_calibration",
    "project_cover", "labs_image",
]


# ---------------------------------------------------------------------------
# Provider-control intentions (empty/default until Slice 06 verifies support)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GenerationControls:
    """Typed provider-control intentions.

    Slice 06 verifies which controls each route supports via
    :meth:`ImageModelProfile.supported_controls`. The compiler rejects
    unsupported (phantom) controls before transport so no UI/config knob
    implies a provider parameter that is never sent.
    """

    quality: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    guidance_scale: float | None = None
    steps_override: int | None = None

    def is_default(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in ("quality", "negative_prompt", "seed", "guidance_scale", "steps_override")
        )

    def active_controls(self) -> dict[str, object]:
        """Map of control name → value for non-None (active) controls."""
        out: dict[str, object] = {}
        if self.quality is not None:
            out["quality"] = self.quality
        if self.negative_prompt is not None:
            out["negative_prompt"] = self.negative_prompt
        if self.seed is not None:
            out["seed"] = self.seed
        if self.guidance_scale is not None:
            out["guidance_scale"] = self.guidance_scale
        if self.steps_override is not None:
            out["steps_override"] = self.steps_override
        return out

    def to_hash_projection(self) -> str:
        """Stable string projection for the compiled-request hash."""
        return json.dumps(
            {
                "quality": self.quality,
                "negative_prompt": self.negative_prompt,
                "seed": self.seed,
                "guidance_scale": self.guidance_scale,
                "steps_override": self.steps_override,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------------
# Reference instructions
# ---------------------------------------------------------------------------


def _facet_phrase(facets: tuple[str, ...]) -> str:
    """Turn a facet tuple into a natural-language list.

    >>> _facet_phrase(("face", "hair", "build"))
    'face, hair, build'
    """
    cleaned = [f for f in facets if f]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + f" and {cleaned[-1]}"


# Role-based facet vocabulary for contextual (non-subject) references. These
# are NOT carried on the ReferenceAsset (which uses empty facets for
# CONTEXTUAL scope); the compiler assigns them per role so every instruction
# names the exact preserved/ignored facets.
_CONTEXTUAL_PRESERVE: dict[str, tuple[str, ...]] = {
    "location_plate": ("architecture", "landmarks", "materials"),
    "prop": ("object",),
    "style": (
        "medium", "mark-making", "palette", "line weight", "facial modeling",
        "wash density", "edge treatment", "shading", "shadow depth",
        "rendering density", "degree of simplification",
    ),
    "continuity": (),
}

_CONTEXTUAL_IGNORE: dict[str, tuple[str, ...]] = {
    "location_plate": ("depicted content that the active state contradicts",),
    "prop": ("reference backdrop",),
    "style": ("people, objects, scenery, text and caption wording, panels, borders, source composition",),
    "continuity": ("facets incompatible with current states",),
}

_LOCATION_STATE_FACETS = frozenset({
    "architecture", "landmarks", "materials", "damage", "water_level",
    "weather", "light", "atmosphere",
})

_SUBJECT_STYLE_IGNORE = (
    "medium", "mark-making", "palette", "line weight", "shading", "lighting",
    "paper texture", "edge treatment", "rendering density",
)



def compile_reference_instruction(
    asset: ReferenceAsset, index: int
) -> "CompiledReferenceInstruction":
    """Compile one semantic instruction for one selected reference.

    The instruction is provider-independent: it uses a positional
    ``Reference {index}`` marker, never a Reve ``<frame>N</frame>`` tag. Slice 07
    serializes the marker into the provider wire format.

    Instruction text by authority scope and role:

    - **subject / FULL_APPEARANCE** — match active face, hair, build, anatomy,
      and wardrobe (every facet the plan preserved).
    - **subject / IDENTITY_ONLY** — preserve only the named compatible
      identity facets (face, hair, build); explicitly ignore the named
      active-state conflicts (wardrobe, anatomy).
    - **location_plate** — preserve architecture/landmarks/materials that the
      active state does not replace; the active damage/weather/time anchor wins.
    - **prop** — preserve the object; ignore its reference backdrop.
    - **style** — preserve medium/mark-making/palette; ignore depicted content.
    - **continuity** — preserve only facets explicitly compatible with
      current states.
    """
    role = asset.role
    scope = asset.authority_scope
    label = asset.label or asset.entity_id or role
    state_id = asset.appearance_state_id

    if role == "subject":
        preserve_phrase = _facet_phrase(asset.preserve_facets)
        style_ignore = _facet_phrase(_SUBJECT_STYLE_IGNORE)
        if scope is AuthorityScope.FULL_APPEARANCE:
            ignore_clause = ""
            if asset.ignore_facets:
                ignore_clause = f"; ignore {_facet_phrase(asset.ignore_facets)}"
            semantic = (
                f"identity reference for {label} — match {preserve_phrase}"
                f"{ignore_clause}; use this reference for identity, anatomy, and wardrobe only; "
                f"ignore its {style_ignore}; the project style direction is the sole style "
                "authority; do not copy its pose or background"
            )
        elif scope is AuthorityScope.IDENTITY_ONLY:
            ignore_phrase = _facet_phrase(asset.ignore_facets)
            conflict_note = " that conflict with the active appearance state" if state_id else ""
            if state_id:
                semantic = (
                    f"canonical parent reference for {label} — preserve only {preserve_phrase}; "
                    f"ignore {ignore_phrase}{conflict_note}; also ignore its {style_ignore}; "
                    "the active-state anchor overrides changed anatomy, age, proportions, "
                    "or wardrobe; selected art direction owns rendering; "
                    "do not copy its pose or background"
                )
            else:
                semantic = (
                    f"identity reference for {label} — preserve only {preserve_phrase}; "
                    f"ignore {ignore_phrase}{conflict_note}; also ignore its {style_ignore}; "
                    "the project style direction is the sole style authority; do not copy its pose "
                    "or background"
                )
        else:
            # A subject under CONTEXTUAL scope is unusual (shouldn't happen for
            # a finalized plan); fall back to a minimal identity instruction.
            semantic = (
                f"identity reference for {label} — preserve identity facets; "
                f"ignore its {style_ignore}; the project style direction is the sole style "
                "authority; do not copy its pose or background"
            )
    elif role == "location_plate":
        # State-asset plans carry the exact canonical facets that remain
        # compatible and the facets the active state replaces. Legacy/general
        # location refs retain the contextual defaults.
        state_facets = (
            state_id is not None
            and bool(
                (set(asset.preserve_facets) | set(asset.ignore_facets))
                & _LOCATION_STATE_FACETS
            )
        )
        preserve = (
            asset.preserve_facets
            if state_facets else _CONTEXTUAL_PRESERVE["location_plate"]
        )
        preserve_phrase = _facet_phrase(preserve) or "no canonical location facets"
        if state_id:
            ignore_clause = (
                f"; ignore {_facet_phrase(asset.ignore_facets)}"
                if state_facets and asset.ignore_facets else ""
            )
            semantic = (
                f"location reference for {label} — preserve {preserve_phrase} "
                f"that the active state does not replace{ignore_clause}; the "
                "active damage, weather, or time-of-day anchor wins over any "
                "conflicting canonical features"
            )
        else:
            semantic = (
                f"location reference for {label} — preserve {preserve_phrase}"
            )
    elif role == "prop":
        preserve = asset.preserve_facets if state_id else _CONTEXTUAL_PRESERVE["prop"]
        ignore = (*asset.ignore_facets, "reference backdrop") if state_id else _CONTEXTUAL_IGNORE["prop"]
        semantic = (
            f"object reference for {label} — preserve {_facet_phrase(preserve)}; "
            f"ignore {_facet_phrase(ignore)}"
        )
        if state_id:
            semantic += "; the active-state anchor overrides every explicitly changed object facet"
    elif role == "style":
        variation = "candidate-controlled rendering facets" in asset.ignore_facets
        preserve = asset.preserve_facets if variation else _CONTEXTUAL_PRESERVE["style"]
        ignore = (*_CONTEXTUAL_IGNORE["style"], *asset.ignore_facets)
        if variation:
            semantic = (
                f"style variation context for {label} — preserve only "
                f"{_facet_phrase(preserve) or 'the authored thematic inspiration'}; "
                "the candidate's selected art direction owns all changed rendering facets; "
                f"ignore {_facet_phrase(ignore)}"
            )
        else:
            semantic = (
                f"sole visual rendering style authority for {label} — match its exact "
                f"{_facet_phrase(preserve)} consistently; ignore {_facet_phrase(ignore)}. "
                "This is rendering evidence, never scene, lettering, or layout authority."
            )
    elif role == "continuity":
        preserve = _CONTEXTUAL_PRESERVE["continuity"]
        ignore = _CONTEXTUAL_IGNORE["continuity"]
        preserve_clause = f"preserve {_facet_phrase(preserve)}; " if preserve else ""
        semantic = (
            f"visual continuity reference — {preserve_clause}"
            f"ignore {_facet_phrase(ignore)}"
        )
    else:
        semantic = f"reference for {label}"

    if role == "subject":
        instruction_preserve = asset.preserve_facets
        instruction_ignore = tuple(dict.fromkeys((*asset.ignore_facets, *_SUBJECT_STYLE_IGNORE)))
    elif role in {"prop", "style"}:
        instruction_preserve = preserve
        instruction_ignore = ignore
    elif role == "location_plate" and state_facets:
        instruction_preserve = asset.preserve_facets
        instruction_ignore = asset.ignore_facets
    else:
        instruction_preserve = _CONTEXTUAL_PRESERVE.get(role, ())
        instruction_ignore = _CONTEXTUAL_IGNORE.get(role, ())
    return CompiledReferenceInstruction(
        index=index,
        role=role,
        entity_label=label,
        authority_scope=scope,
        preserve_facets=instruction_preserve,
        ignore_facets=instruction_ignore,
        appearance_state_id=state_id,
        semantic_instruction=semantic,
    )


@dataclass(frozen=True, slots=True)
class CompiledReferenceInstruction:
    """One exact semantic instruction for one selected reference.

    ``semantic_instruction`` uses a positional ``Reference {index}`` marker
    (never a provider tag). ``preserve_facets`` / ``ignore_facets`` name the
    exact facets the instruction covers so Slice 07 can serialize without
    re-deriving compatibility.
    """

    index: int
    role: str
    entity_label: str | None
    authority_scope: AuthorityScope
    preserve_facets: tuple[str, ...]
    ignore_facets: tuple[str, ...]
    appearance_state_id: str | None
    semantic_instruction: str

    @property
    def marker(self) -> str:
        """Provider-independent positional marker (e.g. ``Reference 0``)."""
        return f"Reference {self.index}"


# ---------------------------------------------------------------------------
# Prompt sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtectedAnchor:
    """A protected anchor recorded in the compiled request for provenance."""

    kind: str
    entity_id: str
    name: str
    appearance_state_id: str | None
    text: str


@dataclass(frozen=True, slots=True)
class CompiledPromptSection:
    """One ordered prompt section in the stable compilation order."""

    kind: str
    title: str
    lines: tuple[str, ...]

    @property
    def body(self) -> str:
        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
# Compiled request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompiledGenerationRequest:
    """The one provider-independent compiled generation request.

    Construct exclusively via :func:`compile_generation_request`. Combines the
    canonical prompt IR with the finalized reference plan, selected style,
    route identity, geometry, and controls into one immutable, hashable
    request. Slice 07 serializes this into the provider wire format without
    reinterpreting prompt text, selecting references, or reordering inputs.
    """

    schema_version: int
    asset_kind: AssetKind
    asset_identity: str
    # Route/provider/model identity (configured, NOT observed provider execution identity)
    requested_alias: str | None
    expected_route: ImageRoute
    provider_key: str
    configured_provider_model: str
    # Style
    selected_style_text: str | None
    selected_style_source_hash: str | None
    # Prompt content
    sections: tuple[CompiledPromptSection, ...]
    final_prompt: str
    protected_anchors: tuple[ProtectedAnchor, ...]
    # References (final selection unchanged from Slice 04)
    reference_plan: ReferencePlan
    reference_instructions: tuple[CompiledReferenceInstruction, ...]
    # Geometry
    requested_shape: GenerationShape | None
    effective_dimensions: tuple[int, int]
    # Controls
    controls: GenerationControls
    # Hashes and metadata
    prompt_source_sha256: str | None
    reference_selection_fingerprint: str
    compiled_request_sha256: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


class CompiledRequestError(ValueError):
    """Raised when the compiled request contradicts active-state authority."""


# ---------------------------------------------------------------------------
# Anchor projection
# ---------------------------------------------------------------------------


def _protected_anchors_from_prompt(
    prompt: GenerationPromptInput,
) -> tuple[ProtectedAnchor, ...]:
    """Collect every protected anchor from the prompt (character + location/prop)."""
    out: list[ProtectedAnchor] = []
    for subject in getattr(prompt, "subjects", []) or []:
        identity = (subject.identity or "").strip()
        if identity:
            out.append(ProtectedAnchor(
                kind="character",
                entity_id=subject.character_id or subject.name,
                name=subject.name,
                appearance_state_id=subject.appearance_state_id,
                text=identity,
            ))
    for anchor in getattr(prompt, "anchors", []) or []:
        text = (anchor.text or "").strip()
        if text:
            out.append(ProtectedAnchor(
                kind=anchor.kind,
                entity_id=anchor.entity_id,
                name=anchor.name,
                appearance_state_id=anchor.appearance_state_id,
                text=text,
            ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Active-state validation
# ---------------------------------------------------------------------------


def _validate_active_state_authority(
    prompt: GenerationPromptInput, plan: ReferencePlan
) -> None:
    """Fail before transport when a selected reference contradicts active state.

    The ReferencePlan already excludes contradictory references (state-conflict
    drops, stale-lineage drops). This is a compiler-level backstop that catches
    one specific plan bug: a FULL_APPEARANCE base-look ref (no recorded state)
    selected for a subject the prompt places in a locked, visually-significant
    state. Such a ref would condition the model on the character's canonical
    appearance and contradict the active state.

    Other mismatches (e.g. a FULL_APPEARANCE ref carrying a non-None state id
    that differs from the prompt's subject state) are prevented upstream by
    Slice 04's state-directory selection logic, so this guard only needs to
    cover the base-look-for-locked-state case.
    """
    subject_states: dict[str, str | None] = {
        s.character_id: s.appearance_state_id
        for s in getattr(prompt, "subjects", []) or []
        if s.character_id
    }
    for asset in plan.selected:
        if asset.role != "subject":
            continue
        if asset.entity_id and asset.entity_id in subject_states:
            prompt_state = subject_states[asset.entity_id]
            asset_state = asset.appearance_state_id
            # A base-look ref (no state) used for a subject in a significant
            # state is only valid under IDENTITY_ONLY (minor state) or
            # canonical_equivalent. The plan already handles this; this guard
            # catches a plan bug where a FULL_APPEARANCE base ref is selected
            # for a locked significant state.
            if (
                asset_state is None
                and prompt_state is not None
                and asset.authority_scope is AuthorityScope.FULL_APPEARANCE
            ):
                locked = any(
                    s.character_id == asset.entity_id
                    and getattr(s, "appearance_locked", False)
                    and not getattr(s, "appearance_state_canonical_equivalent", False)
                    for s in getattr(prompt, "subjects", []) or []
                )
                if locked:
                    raise CompiledRequestError(
                        f"subject {asset.entity_id} is in significant state "
                        f"{prompt_state!r} but a FULL_APPEARANCE base-look ref "
                        f"was selected — the reference would contradict the "
                        "active state"
                    )


# ---------------------------------------------------------------------------
# Compiled-request hash
# ---------------------------------------------------------------------------


def _compiled_hash_projection(req: CompiledGenerationRequest) -> str:
    """Stable SHA-256 over provider-independent execution fields.

    Excludes diagnostics (dropped candidates, warnings) and timestamps.
    Includes: schema, asset identity, route/model fields, style text+hash,
    the final prompt, selection fingerprint (which covers selected content
    hashes but NOT dropped candidates), geometry, and controls.

    Therefore: changing a selected reference's bytes changes the hash (via the
    selection fingerprint); changing an unselected diagnostic candidate does
    not. Changing the style text changes the hash even when the prompt source
    hash is unchanged (style is generation-time-only input excluded from
    Slice 03's stored hash).
    """
    payload = json.dumps(
        {
            "schema_version": req.schema_version,
            "asset_kind": req.asset_kind,
            "asset_identity": req.asset_identity,
            "requested_alias": req.requested_alias,
            "expected_route": req.expected_route.value,
            "provider_key": req.provider_key,
            "configured_provider_model": req.configured_provider_model,
            "selected_style_text": req.selected_style_text,
            "selected_style_source_hash": req.selected_style_source_hash,
            "final_prompt": req.final_prompt,
            "protected_anchors": [
                {
                    "kind": a.kind,
                    "entity_id": a.entity_id,
                    "name": a.name,
                    "appearance_state_id": a.appearance_state_id,
                    "text": a.text,
                }
                for a in req.protected_anchors
            ],
            "reference_selection_fingerprint": req.reference_selection_fingerprint,
            "requested_shape": req.requested_shape,
            "effective_dimensions": list(req.effective_dimensions),
            "controls": json.loads(req.controls.to_hash_projection()),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Geometry projection
# ---------------------------------------------------------------------------


def _effective_geometry(
    prompt: GenerationPromptInput,
) -> tuple[GenerationShape | None, tuple[int, int]]:
    """Resolve the effective target shape and dimensions from the prompt.

    All aspect/dimension math flows through ``image_geometry`` — no inline math.
    """
    gen_shape = getattr(prompt, "generation_shape", None)
    gen_width = getattr(prompt, "generation_width", None)
    gen_height = getattr(prompt, "generation_height", None)
    shape: GenerationShape | None = gen_shape or generation_shape_for_aspect(
        aspect_for_dimensions(prompt.width, prompt.height)
    )
    dimensions = (
        int(gen_width or prompt.width),
        int(gen_height or prompt.height),
    )
    return shape, dimensions


# ---------------------------------------------------------------------------
# Prompt-section assembly (stable order)
# ---------------------------------------------------------------------------


_NAMED_STYLE_ATTRIBUTION_PATTERNS = (
    # "referencing the dark illustration style of Jane Doe"
    re.compile(
        r",?\s*referenc(?:ing|e|ed)\s+the\s+[^.;]*?\s+style\s+of\s+[^.;]+",
        re.IGNORECASE,
    ),
    # "in the style of Jane Doe" / "in Jane Doe's style"
    re.compile(r",?\s*in\s+the\s+style\s+of\s+[^.;]+", re.IGNORECASE),
    # "inspired by Jane Doe"
    re.compile(r",?\s*inspired\s+by\s+[^.;]+", re.IGNORECASE),
)


def _demote_named_style_attributions(style_text: str) -> str:
    """Remove named-style priors once an approved visual reference exists.

    The stored selected style remains untouched for provenance. Only the
    provider-bound projection is cleaned, letting the approved image—not a
    broad named-artist prior—own the rendering grammar.
    """
    cleaned = style_text
    for pattern in _NAMED_STYLE_ATTRIBUTION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return re.sub(r"\s+([,.;])", r"\1", re.sub(r"\s{2,}", " ", cleaned)).strip()


def _build_sections(
    prompt: GenerationPromptInput,
    style_text: str | None,
    reference_instructions: tuple[CompiledReferenceInstruction, ...],
    controls: GenerationControls,
    dimensions: tuple[int, int],
    shape: GenerationShape | None,
    native_aspect: str | None,
    asset_kind: AssetKind,
    dimensions_are_intent: bool = False,
) -> tuple[tuple[CompiledPromptSection, ...], str]:
    """Assemble prompt sections in one stable order and the final prompt.

    Slice 06 — prompt hygiene applied here:

    - Editable scene fields (composition, setting, lighting, mood, key objects,
      visual requirements, continuity, user addenda) are text-sanitized.
    - ``visual_requirements`` are deduplicated against owned facts and capped.
    - Hardcoded medium directives (gouache/oil/etc.) are stripped from scene
      direction; medium guidance derives from the selected style.
    - Native aspect is recorded structurally in the geometry section.
    """
    sections: list[CompiledPromptSection] = []
    has_style_reference = any(
        instruction.role == "style"
        and "candidate-controlled rendering facets" not in instruction.ignore_facets
        for instruction in reference_instructions
    )
    has_subject_references = any(
        instruction.role == "subject" for instruction in reference_instructions
    )
    clean_dynamic = _clean if asset_kind == "style_sample" else sanitize_dynamic_text

    # ── 1. Protected anchors (verbatim — NEVER sanitized) ────────────────
    anchor_lines: list[str] = []
    emitted: set[tuple[str, str | None, str]] = set()
    for subject in prompt.subjects:
        key = (subject.character_id or subject.name, subject.appearance_state_id, subject.identity)
        if subject.identity and key not in emitted:
            anchor_lines.append(f"{subject.name} [{key[0]} / {key[1] or 'canonical'}]: {subject.identity}")
            emitted.add(key)
        if subject.appearance_guard:
            anchor_lines.append(f"{subject.name} continuity guard: {subject.appearance_guard}")
    for anchor in prompt.anchors:
        key = (anchor.entity_id, anchor.appearance_state_id, anchor.text)
        if anchor.text and key not in emitted:
            anchor_lines.append(f"{anchor.name} [{anchor.entity_id} / {anchor.appearance_state_id or 'canonical'}]: {anchor.text}")
            emitted.add(key)
        if anchor.continuity_guard:
            anchor_lines.append(f"{anchor.name} continuity guard: {anchor.continuity_guard}")
    if anchor_lines:
        sections.append(CompiledPromptSection(
            kind="protected_anchors",
            title="Protected anchors",
            lines=tuple(anchor_lines),
        ))

    # ── 2. Scene direction (sanitized editable fields) ───────────────────
    direction_lines: list[str] = []
    for subject in prompt.subjects:
        for field_name in ("action", "position", "expression"):
            value = clean_dynamic(getattr(subject, field_name))
            if value:
                direction_lines.append(f"{subject.name} {field_name}: {value}")
    for field_name, label in (
        ("composition", "Composition"),
        ("setting", "Setting"),
        ("lighting", "Lighting"),
        ("mood", "Mood"),
    ):
        # Dynamic fields are sanitized; protected anchors are emitted above
        # verbatim and never reach this path.
        value = clean_dynamic(getattr(prompt, field_name, None))
        # Strip any hardcoded medium directive that contradicts the style.
        value = strip_hardcoded_mediums(value)
        if value:
            direction_lines.append(f"{label}: {value}")
    props = getattr(prompt, "props", []) or []
    if props:
        cleaned = [clean_dynamic(p) for p in props if clean_dynamic(p)]
        if cleaned:
            direction_lines.append(f"Key props: {'; '.join(cleaned)}")
    key_objects = (
        [
            cleaned
            for value in (getattr(prompt, "key_objects", []) or [])
            if (cleaned := clean_dynamic(value))
        ]
        if asset_kind == "style_sample"
        else sanitize_dynamic_list(getattr(prompt, "key_objects", []) or [])
    )
    if key_objects:
        direction_lines.append(f"Key objects: {'; '.join(key_objects)}")
    # Visual requirements are deduplicated against owned facts and capped.
    deduped_reqs, _ = dedupe_visual_requirements(prompt)
    if deduped_reqs:
        direction_lines.append(f"Must show: {'; '.join(deduped_reqs)}")
    continuity = clean_dynamic(getattr(prompt, "continuity_note", None))
    if continuity:
        direction_lines.append(f"Continuity: {continuity}")
    brief = (
        clean_dynamic(getattr(prompt, "visual_brief", None))
        or clean_dynamic(getattr(prompt, "distilled_prompt", None))
        or clean_dynamic(getattr(prompt, "full_prompt", None))
    )
    brief = dedupe_brief_against_continuity(brief, continuity)
    brief = strip_hardcoded_mediums(brief)
    if brief:
        direction_lines.append(f"Visual brief: {brief}")
    if direction_lines:
        sections.append(CompiledPromptSection(
            kind="scene_direction",
            title="Scene direction",
            lines=tuple(direction_lines),
        ))

    # ── 3. Selected style (medium guidance owner — appears once) ─────────
    cleaned_style = _clean(style_text or getattr(prompt, "style", None))
    if asset_kind != "style_sample":
        from novel_to_comic.style_contract import rendering_style_template

        cleaned_style = rendering_style_template(cleaned_style)
    if cleaned_style:
        if has_style_reference:
            cleaned_style = _demote_named_style_attributions(cleaned_style)
        sections.append(CompiledPromptSection(
            kind="style",
            title=("Secondary style notes" if has_style_reference else "Style"),
            lines=((
                "Secondary textual style notes; the approved visual style reference "
                f"overrides any conflict: {cleaned_style}"
            ) if has_style_reference else cleaned_style,),
        ))

    # ── 4. Reference instructions (semantic, final order) ────────────────
    if reference_instructions:
        ref_lines = tuple(
            f"{instr.marker}: {instr.semantic_instruction}"
            for instr in reference_instructions
        )
        sections.append(CompiledPromptSection(
            kind="reference_instructions",
            title="Reference images",
            lines=ref_lines,
        ))

    # ── 5. System constraints (generated from typed fields) ──────────────
    from novel_to_comic.generation_prompt import generate_system_constraints

    system_lines = generate_system_constraints(
        prompt,
        asset_kind=asset_kind,
        has_style_reference=has_style_reference,
        has_subject_references=has_subject_references,
    )
    if system_lines:
        sections.append(CompiledPromptSection(
            kind="system_constraints",
            title="Constraints",
            lines=tuple(f"- {line.strip()}" for line in system_lines),
        ))

    # ── 6. User constraint addenda (sanitized) ───────────────────────────
    user_constraints = getattr(prompt, "constraints", None)
    if prompt.editorial_addendum:
        addendum = clean_dynamic(prompt.editorial_addendum)
        sections.append(CompiledPromptSection(
            kind="user_addenda",
            title="Authorized editable appearance",
            lines=(
                "Only these editable facets may supersede anchor or reference appearance: "
                + ", ".join(prompt.editable_facets)
                + ". Identity, age, anatomy, explicit state changes, continuity guards, selected style, "
                "and task geometry remain binding. All unedited facets remain unchanged.",
                addendum,
            ),
        ))
    if user_constraints:
        sections.append(CompiledPromptSection(
            kind="user_addenda",
            title="User constraint notes",
            lines=(user_constraints,),
        ))

    # ── 7. Generation geometry ───────────────────────────────────────────
    width, height = dimensions
    geo_lines = [
        (f"Requested composition dimensions (intent, not an enforced output size): {width}x{height}"
         if dimensions_are_intent else f"Output dimensions: {width}x{height}")
    ]
    if shape:
        geo_lines.append(f"Output shape: {shape}")
    if native_aspect:
        geo_lines.append(f"Native aspect: {native_aspect}")
    active = controls.active_controls()
    if active:
        geo_lines.append(f"Controls: {controls.to_hash_projection()}")
    sections.append(CompiledPromptSection(
        kind="geometry",
        title="Generation geometry",
        lines=tuple(geo_lines),
    ))

    order = {"system_constraints": 0, "style": 1, "protected_anchors": 2,
             "reference_instructions": 3, "scene_direction": 4, "user_addenda": 5, "geometry": 6}
    sections.sort(key=lambda section: order[section.kind])
    final_prompt = "\n\n".join(f"{s.title}\n{s.body}" for s in sections if s.lines)
    return tuple(sections), final_prompt


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile_generation_request(
    *,
    prompt: GenerationPromptInput,
    reference_plan: ReferencePlan,
    route_profile: ImageModelProfile,
    requested_alias: str | None = None,
    configured_provider_model: str = "",
    selected_style_text: str | None = None,
    selected_style_source_hash: str | None = None,
    controls: GenerationControls | None = None,
    asset_kind: AssetKind,
    asset_identity: str | None = None,
) -> CompiledGenerationRequest:
    """Compile one provider-independent generation request.

    Pure function of prepared canonical IR, the final ``ReferencePlan``, route
    profile, generation shape, and explicit control intentions. No file
    discovery, LLM call, persistence, or provider call occurs inside it.

    Raises :class:`CompiledRequestError` when:

    - A selected reference's authority scope contradicts the prompt's active
      state (fail before transport).
    - A control intention is not supported by the route (phantom control).
    - Protected material alone exceeds the route's prompt character budget
      (cannot be trimmed safely; no provider may prefix-slice it).
    """
    # Validate active-state authority before building anything.
    _validate_active_state_authority(prompt, reference_plan)
    if reference_plan.expected_route != route_profile.route:
        raise CompiledRequestError("reference plan route differs from selected image profile")
    if len(reference_plan.selected) > route_profile.max_references:
        raise CompiledRequestError("required references exceed selected image profile limit")
    if any(asset.role not in route_profile.supported_roles for asset in reference_plan.selected):
        raise CompiledRequestError("required reference role is unsupported by selected image profile")

    controls = controls or GenerationControls()
    # Slice 06: reject phantom controls the route does not support.
    _validate_control_support(controls, route_profile)

    shape, dimensions = _effective_geometry(prompt)
    native_aspect = _native_aspect_for(prompt, route_profile, shape, dimensions)
    # Compile one semantic instruction per selected reference (final order).
    reference_instructions = tuple(
        compile_reference_instruction(asset, index)
        for index, asset in enumerate(reference_plan.selected)
    )

    sections, final_prompt = _build_sections(
        prompt, selected_style_text, reference_instructions, controls,
        dimensions, shape, native_aspect, asset_kind,
        dimensions_are_intent=route_profile.provider_key == "codex-dev",
    )

    # Slice 06: section-aware budget. Protected sections (anchors, reference
    # instructions, system constraints) are non-truncatable; lower-priority
    # scene prose is compressed first. If protected material alone exceeds the
    # budget, fail explicitly so no provider prefix-slices it later.
    char_limit = route_profile.prompt_char_limit
    budget = apply_prompt_budget(
        [(s.kind, f"{s.title}\n{s.body}") for s in sections], char_limit=char_limit,
    )
    if budget.overshoot > 0:
        raise CompiledRequestError(
            f"protected prompt material exceeds the {route_profile.route.value} "
            f"character budget by {budget.overshoot} characters; cannot trim "
            "protected sections — reduce protected anchor count or length"
        )
    if budget.budgeted:
        final_prompt = budget.final_prompt
        retained_kinds = {kind for kind, _body in budget.retained_sections}
        sections = tuple(section for section in sections if section.kind in retained_kinds)

    protected = _protected_anchors_from_prompt(prompt)
    identity = asset_identity or _default_asset_identity(prompt, asset_kind)

    # Slice 06: structured diagnostics for protected-anchor/no-lettering
    # conflicts. The anchor is preserved verbatim; the no-lettering constraint
    # is retained. These are warnings (non-blocking) surfaced for upstream
    # correction — diagnostics do not affect the compiled hash.
    anchor_conflicts = (
        ()
        if asset_kind == "style_sample"
        else detect_anchor_text_conflicts(prompt)
    )
    warnings = list(reference_plan.warnings)
    for conflict in anchor_conflicts:
        warnings.append(
            f"anchor_text_conflict: {conflict.name} anchor contains '{conflict.cue}' "
            f"(no-lettering policy) — preserved verbatim; correct upstream"
        )

    # Build the request without the hash first, then compute it.
    req = CompiledGenerationRequest(
        schema_version=COMPILED_REQUEST_SCHEMA_VERSION,
        asset_kind=asset_kind,
        asset_identity=identity,
        requested_alias=requested_alias,
        expected_route=route_profile.route,
        provider_key=route_profile.provider_key,
        configured_provider_model=configured_provider_model,
        selected_style_text=_clean(selected_style_text) or None,
        selected_style_source_hash=selected_style_source_hash,
        sections=sections,
        final_prompt=final_prompt,
        protected_anchors=protected,
        reference_plan=reference_plan,
        reference_instructions=reference_instructions,
        requested_shape=shape,
        effective_dimensions=dimensions,
        controls=controls,
        prompt_source_sha256=getattr(prompt, "source_sha256", None),
        reference_selection_fingerprint=reference_plan.selection_fingerprint,
        compiled_request_sha256="",  # placeholder; computed below
        warnings=tuple(warnings),
    )
    # Recompute with the real hash. ``object.__setattr__`` because the
    # dataclass is frozen.
    compiled_hash = _compiled_hash_projection(req)
    object.__setattr__(req, "compiled_request_sha256", compiled_hash)
    return req


def _validate_control_support(controls: GenerationControls, profile: ImageModelProfile) -> None:
    """Reject control intentions the route does not support.

    A phantom control is a UI/config knob that implies a provider parameter the
    route never sends. Failing here prevents a control from silently having no
    effect (or, worse, implying a parameter that a later provider change might
    misinterpret).
    """
    active = controls.active_controls()
    for name in active:
        if not profile.supports_control(name):
            raise CompiledRequestError(
                f"control '{name}' is not supported by route "
                f"{profile.route.value} — supported: "
                f"{sorted(profile.supported_controls) or 'none'}"
            )


def _native_aspect_for(
    prompt: GenerationPromptInput,
    profile: ImageModelProfile,
    shape: GenerationShape | None,
    dimensions: tuple[int, int],
) -> str | None:
    """Resolve the structural native aspect mode for the geometry section.

    Represents aspect structurally when the route has a dedicated aspect
    parameter. Returns ``None`` when the route derives aspect from width/height
    only. A short prose aspect cue is emitted by the compiler (here) — never
    added later by a handler (global invariant: handlers serialize, they do not
    add semantic prose).
    """
    aspect_ratio = getattr(prompt, "generation_aspect_ratio", None)
    if aspect_ratio is None:
        aspect_ratio = aspect_for_dimensions(*dimensions)
    return profile.native_aspect_for(aspect_ratio)


def _default_asset_identity(
    prompt: GenerationPromptInput,
    asset_kind: AssetKind,
) -> str:
    return asset_kind


__all__ = [
    "COMPILED_REQUEST_SCHEMA_VERSION",
    "AssetKind",
    "CompiledGenerationRequest",
    "CompiledPromptSection",
    "CompiledReferenceInstruction",
    "CompiledRequestError",
    "GenerationControls",
    "ProtectedAnchor",
    "compile_generation_request",
    "compile_reference_instruction",
]
