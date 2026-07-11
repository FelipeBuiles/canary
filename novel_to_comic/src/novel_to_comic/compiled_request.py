"""Slice 05 — the one provider-independent compiled generation request.

``compile_generation_request`` is a PURE function that combines the prepared
canonical prompt IR (:class:`~novel_to_comic.models.prompt.ImagePrompt`) with
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

What the compiler does NOT do
-----------------------------

- No file discovery, LLM call, persistence, or provider call.
- No provider-specific serialization (Reve ``<img>N</img>``, signed URLs,
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
from dataclasses import dataclass, field
from typing import Literal

from novel_to_comic.image_models import ImageModelProfile, ImageRoute
from novel_to_comic.image_references import (
    AuthorityScope,
    ReferenceAsset,
    ReferencePlan,
)
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.panel_aspect import (
    GenerationShape,
    aspect_for_dimensions,
    dimensions_for_generation_shape,
    generation_shape_for_aspect,
)
from novel_to_comic.text_utils import clean as _clean

#: Compiler/schema version. Bumped when the compiled-request shape changes.
COMPILED_REQUEST_SCHEMA_VERSION = 1

AssetKind = Literal["panel", "character_ref", "location_plate", "prop_ref", "style_sample"]


# ---------------------------------------------------------------------------
# Provider-control intentions (empty/default until Slice 06 verifies support)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GenerationControls:
    """Typed provider-control intentions.

    Slice 06 verifies which controls each route supports. Until then these are
    defaults: no negative prompt, no seed pinning, no explicit guidance/steps
    override. The compiler carries them so the compiled hash already covers
    control intent for routes that later gain verified support.
    """

    negative_prompt: str | None = None
    seed: int | None = None
    guidance_scale: float | None = None
    steps_override: int | None = None

    def is_default(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in ("negative_prompt", "seed", "guidance_scale", "steps_override")
        )

    def to_hash_projection(self) -> str:
        """Stable string projection for the compiled-request hash."""
        return json.dumps(
            {
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
    "style": ("medium", "mark-making", "palette"),
    "continuity": (),
}

_CONTEXTUAL_IGNORE: dict[str, tuple[str, ...]] = {
    "location_plate": ("depicted content that the active state contradicts",),
    "prop": ("reference backdrop",),
    "style": ("depicted content",),
    "continuity": ("facets incompatible with current states",),
}


def compile_reference_instruction(
    asset: ReferenceAsset, index: int
) -> "CompiledReferenceInstruction":
    """Compile one semantic instruction for one selected reference.

    The instruction is provider-independent: it uses a positional
    ``Reference {index}`` marker, never a Reve ``<img>N</img>`` tag. Slice 07
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
        if scope is AuthorityScope.FULL_APPEARANCE:
            ignore_clause = ""
            if asset.ignore_facets:
                ignore_clause = f"; ignore {_facet_phrase(asset.ignore_facets)}"
            semantic = (
                f"identity reference for {label} — match {preserve_phrase}"
                f"{ignore_clause}; do not copy its pose or background"
            )
        elif scope is AuthorityScope.IDENTITY_ONLY:
            ignore_phrase = _facet_phrase(asset.ignore_facets)
            conflict_note = " that conflict with the active appearance state" if state_id else ""
            semantic = (
                f"identity reference for {label} — preserve only {preserve_phrase}; "
                f"ignore {ignore_phrase}{conflict_note}; do not copy its pose or background"
            )
        else:
            # A subject under CONTEXTUAL scope is unusual (shouldn't happen for
            # a finalized plan); fall back to a minimal identity instruction.
            semantic = (
                f"identity reference for {label} — preserve identity facets; "
                "do not copy its pose or background"
            )
    elif role == "location_plate":
        preserve = _CONTEXTUAL_PRESERVE["location_plate"]
        preserve_phrase = _facet_phrase(preserve)
        if state_id:
            semantic = (
                f"location reference for {label} — preserve {preserve_phrase} "
                "that the active state does not replace; the active damage, "
                "weather, or time-of-day anchor wins over any conflicting "
                "canonical features"
            )
        else:
            semantic = (
                f"location reference for {label} — preserve {preserve_phrase}"
            )
    elif role == "prop":
        preserve = _CONTEXTUAL_PRESERVE["prop"]
        ignore = _CONTEXTUAL_IGNORE["prop"]
        semantic = (
            f"object reference for {label} — preserve {_facet_phrase(preserve)}; "
            f"ignore {_facet_phrase(ignore)}"
        )
    elif role == "style":
        preserve = _CONTEXTUAL_PRESERVE["style"]
        ignore = _CONTEXTUAL_IGNORE["style"]
        semantic = (
            f"style reference for {label} — preserve {_facet_phrase(preserve)}; "
            f"ignore {_facet_phrase(ignore)}"
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

    return CompiledReferenceInstruction(
        index=index,
        role=role,
        entity_label=label,
        authority_scope=scope,
        preserve_facets=asset.preserve_facets if role == "subject" else _CONTEXTUAL_PRESERVE.get(role, ()),
        ignore_facets=asset.ignore_facets if role == "subject" else _CONTEXTUAL_IGNORE.get(role, ()),
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
    # Route/model identity (configured, NOT observed provider execution identity)
    requested_alias: str | None
    expected_route: ImageRoute
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


def _protected_anchors_from_prompt(prompt: ImagePrompt) -> tuple[ProtectedAnchor, ...]:
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
    prompt: ImagePrompt, plan: ReferencePlan
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


def _effective_geometry(prompt: ImagePrompt) -> tuple[GenerationShape | None, tuple[int, int]]:
    """Resolve the effective target shape and dimensions from the prompt.

    All aspect/dimension math flows through ``panel_aspect`` — no inline math.
    """
    gen_shape = getattr(prompt, "generation_shape", None)
    gen_width = getattr(prompt, "generation_width", None)
    gen_height = getattr(prompt, "generation_height", None)
    if gen_shape:
        shape: GenerationShape | None = gen_shape
        dimensions = dimensions_for_generation_shape(gen_shape)
    elif gen_width and gen_height:
        aspect = aspect_for_dimensions(gen_width, gen_height)
        shape = generation_shape_for_aspect(aspect)
        dimensions = (int(gen_width), int(gen_height))
    else:
        width = getattr(prompt, "width", 0)
        height = getattr(prompt, "height", 0)
        aspect = aspect_for_dimensions(width, height)
        shape = generation_shape_for_aspect(aspect) if aspect else None
        dimensions = (int(width), int(height))
    return shape, dimensions


# ---------------------------------------------------------------------------
# Prompt-section assembly (stable order)
# ---------------------------------------------------------------------------


def _build_sections(
    prompt: ImagePrompt,
    style_text: str | None,
    reference_instructions: tuple[CompiledReferenceInstruction, ...],
    controls: GenerationControls,
    dimensions: tuple[int, int],
    shape: GenerationShape | None,
) -> tuple[tuple[CompiledPromptSection, ...], str]:
    """Assemble prompt sections in one stable order and the final prompt.

    Section order:
    1. Protected anchors (character identity + location/prop) — verbatim.
    2. Scene direction (canonical body minus anchors/constraints, i.e. the
       editable scene-direction fields).
    3. Selected style text.
    4. Reference instructions (one per selected reference, final order).
    5. System constraints (generated from typed fields).
    6. User constraint addenda.
    7. Generation geometry.

    The final semantic prompt string concatenates every section body. Protected
    anchors appear byte-for-byte because ``render_canonical_body`` emits them
    unchanged and this function extracts them into their own section.
    """
    sections: list[CompiledPromptSection] = []

    # ── 1. Protected anchors (verbatim) ───────────────────────────────────
    anchor_lines: list[str] = []
    for subject in getattr(prompt, "subjects", []) or []:
        identity = (subject.identity or "").strip()
        if identity:
            anchor_lines.append(f"{subject.name}: {identity}")
    for anchor in getattr(prompt, "anchors", []) or []:
        text = (anchor.text or "").strip()
        if text:
            anchor_lines.append(f"{anchor.name}: {text}")
    if anchor_lines:
        sections.append(CompiledPromptSection(
            kind="protected_anchors",
            title="Protected anchors",
            lines=tuple(anchor_lines),
        ))

    # ── 2. Scene direction (editable fields, NO anchors/constraints) ─────
    direction_lines: list[str] = []
    for field_name, label in (
        ("composition", "Composition"),
        ("setting", "Setting"),
        ("lighting", "Lighting"),
        ("mood", "Mood"),
    ):
        value = _clean(getattr(prompt, field_name, None))
        if value:
            direction_lines.append(f"{label}: {value}")
    props = getattr(prompt, "props", []) or []
    if props:
        cleaned = [_clean(p) for p in props if _clean(p)]
        if cleaned:
            direction_lines.append(f"Key props: {'; '.join(cleaned)}")
    key_objects = [_clean(v) for v in (getattr(prompt, "key_objects", []) or []) if _clean(v)]
    if key_objects:
        direction_lines.append(f"Key objects: {'; '.join(key_objects)}")
    requirements = [_clean(v) for v in (getattr(prompt, "visual_requirements", []) or []) if _clean(v)]
    if requirements:
        direction_lines.append(f"Must show: {'; '.join(requirements)}")
    continuity = _clean(getattr(prompt, "continuity_note", None))
    if continuity:
        direction_lines.append(f"Continuity: {continuity}")
    # The visual brief / distilled prompt is the scene-direction prose body.
    brief = _clean(getattr(prompt, "visual_brief", None)) or _clean(
        getattr(prompt, "distilled_prompt", None)
    )
    if brief:
        direction_lines.append(f"Visual brief: {brief}")
    if direction_lines:
        sections.append(CompiledPromptSection(
            kind="scene_direction",
            title="Scene direction",
            lines=tuple(direction_lines),
        ))

    # ── 3. Selected style ────────────────────────────────────────────────
    cleaned_style = _clean(style_text or getattr(prompt, "style", None))
    if cleaned_style:
        sections.append(CompiledPromptSection(
            kind="style",
            title="Style",
            lines=(cleaned_style,),
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

    system_lines = generate_system_constraints(prompt)
    if system_lines:
        sections.append(CompiledPromptSection(
            kind="system_constraints",
            title="Constraints",
            lines=tuple(f"- {line.strip()}" for line in system_lines),
        ))

    # ── 6. User constraint addenda ───────────────────────────────────────
    user_constraints = _clean(getattr(prompt, "constraints", None))
    if user_constraints:
        sections.append(CompiledPromptSection(
            kind="user_addenda",
            title="User constraint notes",
            lines=tuple(f"- {part.strip()}" for part in user_constraints.split(";") if part.strip()),
        ))

    # ── 7. Generation geometry ───────────────────────────────────────────
    width, height = dimensions
    geo_lines = [f"Output dimensions: {width}x{height}"]
    if shape:
        geo_lines.append(f"Output shape: {shape}")
    if not controls.is_default():
        geo_lines.append(f"Controls: {controls.to_hash_projection()}")
    sections.append(CompiledPromptSection(
        kind="geometry",
        title="Generation geometry",
        lines=tuple(geo_lines),
    ))

    # Final semantic prompt: join section bodies with blank lines.
    final_prompt = "\n\n".join(s.body for s in sections if s.lines)
    return tuple(sections), final_prompt


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile_generation_request(
    *,
    prompt: ImagePrompt,
    reference_plan: ReferencePlan,
    route_profile: ImageModelProfile,
    requested_alias: str | None = None,
    configured_provider_model: str = "",
    selected_style_text: str | None = None,
    selected_style_source_hash: str | None = None,
    controls: GenerationControls | None = None,
    asset_kind: AssetKind = "panel",
    asset_identity: str | None = None,
) -> CompiledGenerationRequest:
    """Compile one provider-independent generation request.

    Pure function of prepared canonical IR, the final ``ReferencePlan``, route
    profile, generation shape, and explicit control intentions. No file
    discovery, LLM call, persistence, or provider call occurs inside it.

    Raises :class:`CompiledRequestError` when a selected reference's authority
    scope contradicts the prompt's active state (fail before transport).
    """
    # Validate active-state authority before building anything.
    _validate_active_state_authority(prompt, reference_plan)

    controls = controls or GenerationControls()
    shape, dimensions = _effective_geometry(prompt)

    # Compile one semantic instruction per selected reference (final order).
    reference_instructions = tuple(
        compile_reference_instruction(asset, index)
        for index, asset in enumerate(reference_plan.selected)
    )

    sections, final_prompt = _build_sections(
        prompt, selected_style_text, reference_instructions, controls, dimensions, shape
    )

    protected = _protected_anchors_from_prompt(prompt)
    identity = asset_identity or _default_asset_identity(prompt, asset_kind)

    # Build the request without the hash first, then compute it.
    req = CompiledGenerationRequest(
        schema_version=COMPILED_REQUEST_SCHEMA_VERSION,
        asset_kind=asset_kind,
        asset_identity=identity,
        requested_alias=requested_alias,
        expected_route=route_profile.route,
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
        warnings=reference_plan.warnings,
    )
    # Recompute with the real hash. ``object.__setattr__`` because the
    # dataclass is frozen.
    compiled_hash = _compiled_hash_projection(req)
    object.__setattr__(req, "compiled_request_sha256", compiled_hash)
    return req


def _default_asset_identity(prompt: ImagePrompt, asset_kind: AssetKind) -> str:
    if asset_kind == "panel":
        return f"{prompt.scene_id}:panel_{prompt.panel_number:03d}"
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
