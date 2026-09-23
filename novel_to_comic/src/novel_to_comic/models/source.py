"""Immutable source-text contracts for the full-page pipeline."""

from __future__ import annotations

import hashlib
import string

from pydantic import BaseModel, ConfigDict, Field, model_validator


_TITLE_ABBREVIATIONS = {
    "dr",
    "jr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "sr",
    "st",
    "vs",
}
_SENTENCE_CLOSERS = {'"', "'", "\u2019", "\u201d", ")", "]"}
_ASCII_LETTERS = frozenset(string.ascii_letters)
_MAX_TITLE_ABBREVIATION = max(len(word) for word in _TITLE_ABBREVIATIONS)


def _follows_title_abbreviation(text: str, index: int) -> bool:
    """Return whether the ASCII word ending before ``index`` is a title.

    Matches ``re.search(r"([A-Za-z]+)$", text[:index])``, including ``$``
    matching before one trailing newline, but scans at most one letter past
    the longest abbreviation instead of copying the prefix.
    """

    end = index
    if end > 0 and text[end - 1] == "\n":
        end -= 1
    start = end
    limit = max(0, end - _MAX_TITLE_ABBREVIATION - 1)
    while start > limit and text[start - 1] in _ASCII_LETTERS:
        start -= 1
    if end - start > _MAX_TITLE_ABBREVIATION:
        return False
    return text[start:end].lower() in _TITLE_ABBREVIATIONS


def sentence_end_offsets(text: str) -> tuple[int, ...]:
    """Return exact unit ends after sentence punctuation and trailing space."""

    offsets: list[int] = []
    index = 0
    while index < len(text):
        mark = text[index]
        if mark not in ".!?":
            index += 1
            continue

        if mark == ".":
            if (
                index > 0
                and index + 1 < len(text)
                and text[index - 1].isdigit()
                and text[index + 1].isdigit()
            ):
                index += 1
                continue
            if _follows_title_abbreviation(text, index):
                index += 1
                continue
            while index + 1 < len(text) and text[index + 1] == ".":
                index += 1

        end = index + 1
        while end < len(text) and text[end] in _SENTENCE_CLOSERS:
            end += 1
        if end < len(text) and not text[end].isspace():
            index = end
            continue
        while end < len(text) and text[end].isspace():
            end += 1
        offsets.append(end)
        index = end

    if not offsets or offsets[-1] != len(text):
        offsets.append(len(text))
    return tuple(offsets)


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


class SourceContextReference(BaseModel):
    """A labeled, non-owning reference to source units outside primary coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    unit_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unit_ids_are_unique(self) -> "SourceContextReference":
        if len(self.unit_ids) != len(set(self.unit_ids)):
            raise ValueError("context reference source unit IDs must be unique")
        return self


class SourceScene(BaseModel):
    """A primary contiguous range plus optional non-owning context units."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    first_unit_id: str = Field(min_length=1)
    last_unit_id: str = Field(min_length=1)
    context: tuple[SourceContextReference, ...] = ()

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
        valid_ends = set(sentence_end_offsets(self.text))
        if any(unit.end_offset not in valid_ends for unit in self.units):
            raise ValueError("source unit boundaries must be sentence-aligned")

        scene_ids = [scene.id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("source scene IDs must be unique")

        ownership = {unit_id: 0 for unit_id in ids}
        expected_scene_start = 0
        for scene in self.scenes:
            primary_unit_ids = scene.unit_ids(self)
            primary_unit_id_set = set(primary_unit_ids)
            for reference in scene.context:
                for context_id in reference.unit_ids:
                    if context_id not in ownership:
                        raise ValueError(
                            f"scene {scene.id!r} references unknown context unit "
                            f"{context_id!r}"
                        )
                    if context_id in primary_unit_id_set:
                        raise ValueError(
                            f"scene {scene.id!r} context must point outside its "
                            "primary range"
                        )
            first_index = ids.index(primary_unit_ids[0])
            if first_index != expected_scene_start:
                raise ValueError(
                    "primary source-scene ranges must be complete and ordered"
                )
            expected_scene_start += len(primary_unit_ids)
            for unit_id in primary_unit_ids:
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
