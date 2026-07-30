"""Provider-independent semantic inputs for Cast asset generation."""

from typing import Literal

from pydantic import BaseModel


class PromptAnchor(BaseModel):
    """One protected Story Bible visual anchor, preserved verbatim."""

    kind: Literal["character", "location", "prop"]
    entity_id: str
    name: str
    appearance_state_id: str | None = None
    text: str


class PromptSubject(BaseModel):
    """One Cast subject and its optional active appearance authority."""

    character_id: str | None = None
    name: str
    identity: str
    action: str = ""
    expression: str = ""
    baseline_affect: str | None = None
    position: str = ""
    appearance_state_id: str | None = None
    appearance_state_canonical_equivalent: bool = False
    appearance_locked: bool = False
    appearance_guard: str | None = None
