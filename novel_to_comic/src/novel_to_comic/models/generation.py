"""Provider-independent semantic inputs for Cast asset generation."""

from typing import Literal

from pydantic import BaseModel

from novel_to_comic.models.appearance import ReferenceForm


class PromptAnchor(BaseModel):
    """One protected Story Bible visual anchor, preserved verbatim."""

    kind: Literal["character", "location", "prop"]
    entity_id: str
    name: str
    appearance_state_id: str | None = None
    text: str
    continuity_guard: str | None = None


class PromptSubject(BaseModel):
    """One Cast subject and its optional active appearance authority."""

    character_id: str | None = None
    name: str
    identity: str
    action: str = ""
    expression: str = ""
    baseline_affect: str | None = None
    # Prose-only renders with no Cast reference (style proofs) carry the
    # Story Bible outfit here; it overrides clothing named in the identity.
    wardrobe: str = ""
    position: str = ""
    appearance_state_id: str | None = None
    appearance_state_canonical_equivalent: bool = False
    appearance_locked: bool = False
    appearance_guard: str | None = None
    # Cast sheets only: which reference layout this subject's sheet uses.
    reference_form: ReferenceForm = "figure"
