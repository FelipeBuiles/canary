"""Deterministic immutable-source construction for target Extract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.source import (
    SourceDocument,
    SourceScene,
    SourceUnit,
    sentence_end_offsets,
)
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.target_artifacts import TargetArtifacts


class SourceSceneAnchor(BaseModel):
    """A Story Bible scene's exact opening sentence and display identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    opening_quote: str = Field(min_length=1)


def _source_units(text: str) -> tuple[SourceUnit, ...]:
    start = 0
    units: list[SourceUnit] = []
    for ordinal, end in enumerate(sentence_end_offsets(text), start=1):
        units.append(
            SourceUnit(
                id=f"source_{ordinal:06d}",
                ordinal=ordinal,
                start_offset=start,
                end_offset=end,
                text=text[start:end],
            )
        )
        start = end
    return tuple(units)


def _unit_for_opening_quote(
    text: str,
    units: tuple[SourceUnit, ...],
    anchor: SourceSceneAnchor,
    *,
    search_from: int,
) -> int:
    position = text.find(anchor.opening_quote, search_from)
    if position == -1:
        raise ValueError(
            f"scene {anchor.id!r} verbatim opening quote was not found in source"
        )
    for unit_index, unit in enumerate(units):
        semantic_start = unit.start_offset + len(unit.text) - len(unit.text.lstrip())
        if position == semantic_start:
            if anchor.opening_quote != unit.text.strip():
                raise ValueError(
                    f"scene {anchor.id!r} anchor must be the complete opening sentence"
                )
            return unit_index
        if unit.start_offset <= position < unit.end_offset:
            raise ValueError(
                f"scene {anchor.id!r} opening quote creates a mid-sentence boundary"
            )
    raise ValueError(f"scene {anchor.id!r} opening quote is outside source units")


def build_source_document(
    text: str,
    scene_anchors: list[SourceSceneAnchor] | tuple[SourceSceneAnchor, ...],
) -> SourceDocument:
    """Build exact sentence units and contiguous primary scene ownership."""

    if not text:
        raise ValueError("source text cannot be empty")
    if not scene_anchors:
        raise ValueError("at least one source scene anchor is required")

    units = _source_units(text)
    boundary_indexes: list[int] = []
    search_from = 0
    for anchor in scene_anchors:
        unit_index = _unit_for_opening_quote(
            text,
            units,
            anchor,
            search_from=search_from,
        )
        if boundary_indexes and unit_index <= boundary_indexes[-1]:
            raise ValueError("source scene anchors must be ordered and non-overlapping")
        boundary_indexes.append(unit_index)
        search_from = units[unit_index].end_offset

    if boundary_indexes[0] != 0:
        raise ValueError("first scene must begin at the first source unit")

    scenes = []
    for index, anchor in enumerate(scene_anchors):
        first = boundary_indexes[index]
        last = (
            boundary_indexes[index + 1] - 1
            if index + 1 < len(boundary_indexes)
            else len(units) - 1
        )
        scenes.append(
            SourceScene(
                id=anchor.id,
                title=anchor.title,
                first_unit_id=units[first].id,
                last_unit_id=units[last].id,
            )
        )

    return SourceDocument(text=text, units=units, scenes=scenes)


def produce_source_document(
    artifacts: TargetArtifacts,
    text: str,
    story_bible: StoryBible,
    /,
) -> SourceDocument:
    """Build and persist Extract's sole canonical source-text artifact."""

    document = build_source_document(
        text,
        tuple(
            SourceSceneAnchor(
                id=scene.id,
                title=scene.title,
                opening_quote=scene.source_start_quote,
            )
            for scene in story_bible.scenes
        ),
    )
    artifacts.write_source(document)
    return document
