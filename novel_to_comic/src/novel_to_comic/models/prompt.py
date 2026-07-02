"""Pydantic models for image prompts."""


from pydantic import BaseModel, Field


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
    """One flat region of a panel layout (no nesting — containment is spatial).

    reference_key binds the region to a reference image: a character id
    (e.g. "char_carl") for subjects or a prop id for props. The draw-stage
    provider resolves it to the Reve `image_index` of the uploaded reference.
    """

    label: str
    prompt: str
    bbox: LayoutBbox = Field(default_factory=LayoutBbox)
    reference_key: str | None = None


class PromptLayout(BaseModel):
    """Flat layout for layout-aware generation (Reve v2 Description shape)."""

    prompt: str | None = None
    regions: list[LayoutRegion] = Field(default_factory=list)

    def sanitized(self) -> "PromptLayout":
        """Drop malformed regions, clamp boxes, and de-duplicate labels.

        Stored layouts come from an LLM or hand edits, so loading stays
        lenient and correctness is enforced here at the generation boundary
        (Reve requires unique labels and boxes within [0, 1]).
        """
        seen: set[str] = set()
        regions: list[LayoutRegion] = []
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
            regions.append(LayoutRegion(
                label=label,
                prompt=prompt,
                bbox=bbox,
                reference_key=region.reference_key,
            ))
        return PromptLayout(prompt=(self.prompt or "").strip() or None, regions=regions)


class PromptSubject(BaseModel):
    character_id: str | None = None
    name: str
    identity: str
    action: str = ""
    expression: str = ""
    position: str = ""
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
    # Effective location state for this panel (panel override, else scene
    # default). Draw uses it to pick the matching per-state location plate.
    location_state_id: str | None = None
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
    reference_image_paths: list[str] = Field(default_factory=list)  # Project-relative paths to character ref images
    width: int
    height: int
    steps: int
    continuity_note: str | None = None
