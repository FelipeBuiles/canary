"""The book map: what the whole saved manuscript holds, at part granularity.

A series' parts are analyzed one at a time, but each part is a stretch of one
book. The map is a light read of every saved part that tells a part where it
sits: the book's acts, the through-lines it opens or pays off, and which of
its people matter beyond it. It is reference context for Extract, Brief and
Adapt, never source to adapt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChapterNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    synopsis: str = Field(min_length=1)


class DigestCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    aliases: list[str] = []
    role: str = Field(min_length=1)
    presence: Literal["central", "supporting", "passing"]


class DigestThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    status: Literal["opens", "advances", "resolves"]
    note: str = Field(min_length=1)


class PartDigest(BaseModel):
    """One part read on its own. Cached by its exact text."""

    model_config = ConfigDict(extra="forbid")

    synopsis: str = Field(min_length=1)
    chapters: list[ChapterNote] = []
    characters: list[DigestCharacter] = []
    threads: list[DigestThread] = []
    motifs: list[str] = []


class BookAct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    # Inclusive part range. Acts follow the book, so a part can end one act
    # and begin the next.
    first_part: str
    last_part: str


class BookThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Code numbers threads in reading order (thread_001...).
    id: str = ""
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    opens_in: str
    # None while the thread is still open at the end of the saved text.
    resolves_in: str | None = None


class BookCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    aliases: list[str] = []
    role: str = Field(min_length=1)
    prominence: Literal["principal", "recurring", "minor"]
    first_part: str
    last_part: str


class BookMapPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_id: str
    # The part text the map read; a changed text makes this entry stale.
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    synopsis: str = Field(min_length=1)
    role: str = Field(min_length=1)


class BookMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    synopsis: str = Field(min_length=1)
    parts: list[BookMapPart] = Field(min_length=1)
    acts: list[BookAct] = Field(min_length=1)
    threads: list[BookThread] = []
    characters: list[BookCharacter] = []
    themes: list[str] = []
    motifs: list[str] = []


class PartRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_id: str
    role: str = Field(min_length=1)


class BookSynthesis(BaseModel):
    """The model's book-level reading; code adds part text bindings."""

    model_config = ConfigDict(extra="forbid")

    synopsis: str = Field(min_length=1)
    acts: list[BookAct] = Field(min_length=1)
    parts: list[PartRole] = Field(min_length=1)
    threads: list[BookThread] = []
    characters: list[BookCharacter] = []
    themes: list[str] = []
    motifs: list[str] = []

