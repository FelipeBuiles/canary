"""Immutable source-text contracts for the full-page pipeline."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceUnit(BaseModel):
    """One stable, ordered slice of the immutable source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _end_follows_start(self) -> "SourceUnit":
        if self.end_offset <= self.start_offset:
            raise ValueError("source unit end_offset must follow start_offset")
        return self


class SourceScene(BaseModel):
    """A primary contiguous range plus optional non-owning context units."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    first_unit_id: str = Field(min_length=1)
    last_unit_id: str = Field(min_length=1)
    context_unit_ids: tuple[str, ...] = ()

    def unit_ids(self, document: "SourceDocument") -> list[str]:
        index = {unit.id: position for position, unit in enumerate(document.units)}
        try:
            first = index[self.first_unit_id]
            last = index[self.last_unit_id]
        except KeyError as exc:
            raise ValueError(f"scene references unknown source unit {exc.args[0]!r}") from exc
        if first > last:
            raise ValueError("scene source-unit range is inverted")
        return [unit.id for unit in document.units[first : last + 1]]


class SourceDocument(BaseModel):
    """The canonical source text and its exact unit/scene index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    source_sha256: str = ""
    units: tuple[SourceUnit, ...] = Field(min_length=1)
    scenes: tuple[SourceScene, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_source_index(self) -> "SourceDocument":
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.source_sha256 and self.source_sha256 != digest:
            raise ValueError("source_sha256 does not match source text")
        object.__setattr__(self, "source_sha256", digest)

        ids = [unit.id for unit in self.units]
        if len(ids) != len(set(ids)):
            raise ValueError("source unit IDs must be unique")
        if [unit.ordinal for unit in self.units] != list(range(1, len(self.units) + 1)):
            raise ValueError("source unit ordinals must be consecutive")

        expected_start = 0
        for unit in self.units:
            if unit.start_offset != expected_start:
                raise ValueError("source units must be contiguous")
            if self.text[unit.start_offset : unit.end_offset] != unit.text:
                raise ValueError(f"source unit {unit.id!r} does not match source text")
            expected_start = unit.end_offset
        if expected_start != len(self.text):
            raise ValueError("source units must cover the complete source text")

        ownership = {unit_id: 0 for unit_id in ids}
        for scene in self.scenes:
            for context_id in scene.context_unit_ids:
                if context_id not in ownership:
                    raise ValueError(
                        f"scene {scene.id!r} references unknown context unit {context_id!r}"
                    )
            for unit_id in scene.unit_ids(self):
                ownership[unit_id] += 1

        incorrectly_owned = [
            unit_id for unit_id, owner_count in ownership.items() if owner_count != 1
        ]
        if incorrectly_owned:
            raise ValueError(
                "every source unit must have exactly one primary scene owner: "
                + ", ".join(incorrectly_owned)
            )
        return self
