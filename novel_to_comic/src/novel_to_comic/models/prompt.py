"""Pydantic models for image prompts."""

from typing import Literal

from pydantic import BaseModel, Field


# Slice 03 — prompt source lineage and freshness.
#
# A user correction is an OVERLAY, not a mutation of the canonical source
# material (anchors, scene direction compiled from the Story Bible). When a
# canonical rebuild happens (upstream change → new source_sha256), the rebuild
# recompiles canonical source, then reapplies every valid overlay, then
# invalidates derived brief/layout. Overlays are keyed to the entity id and
# appearance/location state in which they were authored, so a correction for a
# removed character or an incompatible state is dropped with a structured
# warning rather than silently misapplied.

OverlayField = Literal[
    "composition",
    "setting",
    "lighting",
    "mood",
    "constraints",
    "continuity_note",
    "props",
    "key_objects",
    "visual_requirements",
    # Subject-scoped editable scene direction:
    "action",
    "expression",
    "position",
]

LayoutRegionType = Literal[
    "coarse_detail",
    "medium_detail",
    "fine_detail",
    "text",
    "hand",
    "face",
]


class PromptOverlayOp(BaseModel):
    """One user-authored correction stored as an overlay on a canonical prompt.

    Overlays are replayed after a canonical rebuild. ``field`` is an editable
    scene-direction field (never an identity anchor or system constraint).
    Subject-scoped ops (``action``/``expression``/``position``) carry
    ``subject_character_id`` to bind the correction to one subject rather than
    a positional index, and ``appearance_state_id`` to bind it to one
    appearance state.

    State keying: an op authored while a character is in state ``stumps`` only
    re-apes when that subject is in the ``stumps`` state. ``None`` state id
    means the op is state-neutral (e.g. a framing note) and re-apes whenever
    the subject is present in any state.

    Location-sensitive ops carry ``location_state_id`` so a correction bound to
    a damaged/weathered location state is revalidated when that state activates.
    """

    field: OverlayField
    value: str | list[str]
    subject_character_id: str | None = None
    appearance_state_id: str | None = None
    location_state_id: str | None = None


class OverlayWarning(BaseModel):
    """Structured warning emitted when a stored overlay cannot be reapplied."""

    code: Literal[
        "subject_missing",
        "state_incompatible",
        "location_state_incompatible",
        "value_empty",
    ]
    reason: str
    operation: PromptOverlayOp


class LayoutBbox(BaseModel):
    """Normalized bounding box, top-left origin, values in [0, 1].

    Mirrors the Reve v2 wire format exactly (x0, y0, x1, y1) so a stored
    layout serializes to the API without translation.
    """

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0

    def clamped(self) -> "LayoutBbox | None":
        """Return a copy clamped to [0, 1] with corners ordered, or None when degenerate."""
        x0, x1 = sorted((min(max(self.x0, 0.0), 1.0), min(max(self.x1, 0.0), 1.0)))
        y0, y1 = sorted((min(max(self.y0, 0.0), 1.0), min(max(self.y1, 0.0), 1.0)))
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            return None
        return LayoutBbox(x0=x0, y0=y0, x1=x1, y1=y1)


class LayoutRegion(BaseModel):
    """One region of a panel layout.

    reference_key binds the region to a reference image: a character id
    (e.g. "char_carl") for subjects or a prop id for props. The draw-stage
    compiler resolves it to the Reve `image_index` of the uploaded reference.
    ``parent`` and ``region_type`` are native Reve v2 layout hints; parent
    relationships are optional and are spatially validated during sanitizing.
    """

    label: str
    prompt: str
    bbox: LayoutBbox = Field(default_factory=LayoutBbox)
    reference_key: str | None = None
    parent: str | None = None
    region_type: LayoutRegionType | None = None
    image_region_index: int | None = None


class PromptLayout(BaseModel):
    """Editable layout IR projected to Reve v2's layout render contract."""

    prompt: str | None = None
    normalized_edit_instruction: str | None = None
    regions: list[LayoutRegion] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None

    def sanitized(self) -> "PromptLayout":
        """Drop malformed regions, clamp boxes, and normalize hierarchy.

        Stored layouts come from an LLM or hand edits, so loading stays
        lenient and correctness is enforced here at the generation boundary.
        """
        seen: set[str] = set()
        candidates: list[tuple[LayoutRegion, str, LayoutBbox]] = []
        aliases: dict[str, str] = {}
        for region in self.regions:
            label = (region.label or "").strip()
            prompt = (region.prompt or "").strip()
            if not label or not prompt:
                continue
            bbox = region.bbox.clamped()
            if bbox is None:
                continue
            base = label
            suffix = 2
            while label in seen:
                label = f"{base}_{suffix}"
                suffix += 1
            seen.add(label)
            aliases.setdefault(base, label)
            candidates.append((region, label, bbox))

        labels = {label for _region, label, _bbox in candidates}
        regions: list[LayoutRegion] = []
        for source, label, bbox in candidates:
            parent = (source.parent or "").strip() or None
            if parent:
                parent = aliases.get(parent, parent)
                if parent not in labels or parent == label:
                    parent = None
            reference_key = (source.reference_key or "").strip() or None
            image_region_index = (
                source.image_region_index
                if source.image_region_index is not None and source.image_region_index >= 0
                else None
            )
            regions.append(LayoutRegion(
                label=label,
                prompt=(source.prompt or "").strip(),
                bbox=bbox,
                reference_key=reference_key,
                parent=parent,
                region_type=source.region_type,
                image_region_index=image_region_index,
            ))

        # Reve accepts hierarchical regions, but cyclic parent references are
        # invalid semantics. Clear the offending edge while retaining the
        # otherwise useful region and its spatial box.
        parent_by_label = {region.label: region.parent for region in regions}
        normalized_regions: list[LayoutRegion] = []
        for region in regions:
            normalized_parent = region.parent
            parent = normalized_parent
            chain = {region.label}
            while parent:
                if parent in chain:
                    normalized_parent = None
                    break
                chain.add(parent)
                parent = parent_by_label.get(parent)
            normalized_regions.append(
                region.model_copy(update={"parent": normalized_parent})
            )

        bbox_by_label = {region.label: region.bbox for region in normalized_regions}
        spatial_regions: list[LayoutRegion] = []
        for region in normalized_regions:
            parent_box = bbox_by_label.get(region.parent or "")
            if parent_box and not (
                parent_box.x0 <= region.bbox.x0
                and parent_box.y0 <= region.bbox.y0
                and parent_box.x1 >= region.bbox.x1
                and parent_box.y1 >= region.bbox.y1
            ):
                spatial_regions.append(region.model_copy(update={"parent": None}))
            else:
                spatial_regions.append(region)

        width = self.width if self.width and self.width > 0 and self.width % 32 == 0 else None
        height = self.height if self.height and self.height > 0 and self.height % 32 == 0 else None
        if (width is None) != (height is None):
            width = height = None
        return PromptLayout(
            prompt=(self.prompt or "").strip() or None,
            normalized_edit_instruction=(self.normalized_edit_instruction or "").strip() or None,
            regions=spatial_regions,
            width=width,
            height=height,
        )


class PromptAnchor(BaseModel):
    """A protected, verbatim visual anchor for one entity in a panel.

    Immutable source material (Slice 02): ``text`` is the exact, self-contained
    ``visual_anchor`` from the Story Bible — for a character, the base anchor
    when no state is active, or the active state's anchor otherwise. Never
    shortened, filtered, underscore-replaced, translated, or LLM-rewritten.

    Anchors are owned by the canonical IR and are NOT part of the editable
    scene-direction surface (the LLM visual-brief pass never sees them).
    """

    kind: Literal["character", "location", "prop"]
    entity_id: str
    name: str
    appearance_state_id: str | None = None
    text: str


class PromptSubject(BaseModel):
    character_id: str | None = None
    name: str
    identity: str
    action: str = ""
    expression: str = ""
    position: str = ""
    # The active character appearance state id for this panel (None = base look).
    # Set by the canonical builder from the appearance resolver; the brief and
    # provider paths key off it for per-state reference selection.
    appearance_state_id: str | None = None
    appearance_state_canonical_equivalent: bool = False
    # True when ``identity`` is a non-base, visually-significant appearance state
    # (e.g. stumps, silver hands). The brief pass treats it as a fixed, immutable
    # look and stages actions around it rather than as one fact among many.
    appearance_locked: bool = False
    # Optional authored continuity rule from the active AppearanceState.
    appearance_guard: str | None = None


class ImagePrompt(BaseModel):
    prompt_version: int = 1
    planned_panel_id: str | None = None
    scene_id: str
    panel_number: int
    generation_mode: str | None = None
    shape_intent: str | None = None
    generation_aspect_ratio: float | None = None
    generation_width: int | None = None
    generation_height: int | None = None
    generation_shape: str | None = None
    generation_aspect_source: str | None = None
    crop_policy: str | None = None
    transition_in: str | None = None
    transition_out: str | None = None
    # The scene's location id for this panel (resolved from the Story Bible).
    location_id: str | None = None
    # Effective location state for this panel (panel override, else scene
    # default). Draw uses it to pick the matching per-state location plate.
    location_state_id: str | None = None
    # Protected verbatim visual anchors (Slice 02). Location and prop anchors
    # live here; character anchors live on ``subjects[].identity``. These are
    # immutable source material, never part of the editable scene direction.
    anchors: list[PromptAnchor] = Field(default_factory=list)
    has_narration_caption: bool = False
    narration_mode: str | None = None
    preferred_caption_zone: str | None = None
    full_prompt: str = ""
    distilled_prompt: str | None = None
    # LLM-composed prose visual brief — the preferred generation body.
    # Falls back to distilled_prompt when absent (older prompts, LLM failure).
    visual_brief: str | None = None
    style: str | None = None
    composition: str | None = None
    setting: str | None = None
    lighting: str | None = None
    mood: str | None = None
    subjects: list[PromptSubject] = Field(default_factory=list)
    key_objects: list[str] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    constraints: str | None = None
    # Flat layout-aware region map. Only used when the image model supports
    # regional prompting (Reve v2); other models ignore it.
    layout: PromptLayout | None = None
    width: int
    height: int
    steps: int
    continuity_note: str | None = None
    # Slice 03 — deterministic source lineage. The prompt is current when its
    # stored ``source_sha256`` matches the canonical projection of its inputs.
    # Computed by ``prompt_assembly.compute_source_sha256`` from a sorted,
    # stable projection of the Story Bible + PlannedPanel + appearance state.
    # Generation-time-only inputs (active style text) are excluded: changing
    # style must not rebuild stored panel structure.
    source_sha256: str | None = None
    # User-authored corrections stored as overlays, replayed after a canonical
    # rebuild. Each op is keyed to the entity id + state in which it was
    # authored; see ``PromptOverlayOp``.
    user_overlays: list[PromptOverlayOp] = Field(default_factory=list)
