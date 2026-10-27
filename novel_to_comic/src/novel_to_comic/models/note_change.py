"""One author note carried beyond its page: preview, check, apply and undo."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.note_scope import NoteClaim, NoteScope

NoteChangeStatus = Literal["proposed", "applied", "undone"]


class FactCheck(BaseModel):
    """What one page's current art showed against a look fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    breaks_fact: bool
    panels: tuple[int, ...] = ()
    evidence: str = ""


class NoteStamp(BaseModel):
    """The canonical artifacts a step read or wrote; any drift refuses the next step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adaptation_sha256: str = Field(min_length=64, max_length=64)
    plan_sha256: str = Field(min_length=64, max_length=64)
    story_bible_revision: int = Field(ge=1)


class NoteChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^note_[0-9a-f]{12}$")
    page_number: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=1000)
    claim: NoteClaim
    scope: NoteScope
    status: NoteChangeStatus = "proposed"
    previewed: NoteStamp
    checks: tuple[FactCheck, ...] = ()
    # Pages whose panels the author chose to change, decided at apply.
    pages: tuple[int, ...] = ()
    state_id: str | None = None
    added_state: bool = False
    redraw_pages: tuple[int, ...] = ()
    applied: NoteStamp | None = None
    created_at: str = Field(min_length=1)
    applied_at: str | None = None
    undone_at: str | None = None
