"""Cold Open artifacts: the opening Extract has read, and the pages drawn from it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.story_bible import StoryBible


class OpeningSnapshot(BaseModel):
    """The first part's Story Bible as it stood after Extract read the opening.

    Not an authority: Brief, Style, Cast and every later stage read only the
    published Story Bible. Visual anchors in it are already final, because a
    later section cannot change an existing anchor (``RegistryAnchorConflict``).
    """

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    bible: StoryBible
    # The part text this snapshot covers, from its start. Scene source offsets
    # index into it. Bounded by the Extract section size.
    text: str = Field(min_length=1)
    whole_source: bool


class ColdOpenLook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    medium: str
    status: Literal["queued", "printing", "ready", "failed"] = "queued"
    error: str | None = None


class ColdOpenRecord(BaseModel):
    """One Canary-paid page of the author's opening, in three looks."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    part_id: str
    status: Literal["printing", "ready", "failed"] = "printing"
    scene_id: str | None = None
    scene_title: str = ""
    scene_summary: str = ""
    chapter: int | None = None
    looks: list[ColdOpenLook] = Field(default_factory=list)
    # "model" when the ranking call chose the order, "catalog" for the fallback.
    ranking: Literal["model", "catalog"] = "catalog"
    # The proof's story lines (``ProofCopy``), kept with the pages so a later
    # Style cache refresh never relabels them. None shows role labels.
    proof_copy: dict | None = None
    favorite_look_id: str | None = None
    adopted_look_ids: list[str] = Field(default_factory=list)
    # Provider cost Canary absorbed. Never charged; unknown-cost calls are
    # counted, not guessed.
    provider_cost_usd: float = 0.0
    unknown_cost_calls: int = 0
    started_at: str
    finished_at: str | None = None
