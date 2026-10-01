"""The ordered parts of a series and their immutable source text records."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.workspace import part_id


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PartRecord(BaseModel):
    """One part's identity and the exact source text it was created with.

    The text itself lives beside the manifest; ``text_sha256`` binds the record
    to it so a changed file is detected rather than silently adapted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    characters: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    # Original upload filename, or "paste" for pasted text. Display only.
    origin: str = ""

    @model_validator(mode="after")
    def _id_matches_ordinal(self) -> "PartRecord":
        if self.id != part_id(self.ordinal):
            raise ValueError(f"part id {self.id!r} does not match ordinal {self.ordinal}")
        return self


class PartManifest(BaseModel):
    """The series' parts in reading order. Parts are only ever appended."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    parts: tuple[PartRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> "PartManifest":
        ordinals = [part.ordinal for part in self.parts]
        if ordinals != list(range(1, len(self.parts) + 1)):
            raise ValueError("part ordinals must be consecutive from 1")
        return self

    def get(self, identifier: str) -> PartRecord:
        for part in self.parts:
            if part.id == identifier:
                return part
        raise KeyError(identifier)

    @property
    def latest(self) -> PartRecord:
        return self.parts[-1]

    def previous(self, identifier: str) -> PartRecord | None:
        record = self.get(identifier)
        return self.parts[record.ordinal - 2] if record.ordinal > 1 else None
