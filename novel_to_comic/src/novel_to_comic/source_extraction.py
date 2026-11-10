"""Deterministic immutable-source construction for target Extract."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from difflib import SequenceMatcher
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.source import (
    SourceDocument,
    SourceScene,
    SourceUnit,
    sentence_end_offsets,
)
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.target_artifacts import TargetArtifacts

logger = logging.getLogger("canary.source_extraction")


class SceneOpening(Protocol):
    id: str
    source_start_quote: str
    source_start_offset: int | None


class SourceSceneAnchor(BaseModel):
    """A Story Bible scene's exact opening sentence and display identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    opening_quote: str = Field(min_length=1)
    start_offset: int | None = Field(default=None, ge=0)


def source_units(text: str, *, first_ordinal: int = 1) -> tuple[SourceUnit, ...]:
    """Segment the immutable source once into stable sentence-aligned units.

    A later part's units continue the series ordinals from ``first_ordinal``.
    """

    start = 0
    units: list[SourceUnit] = []
    for ordinal, end in enumerate(sentence_end_offsets(text), start=first_ordinal):
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


def _semantic_start(unit: SourceUnit) -> int:
    """Offset of the unit's first non-whitespace character."""

    return unit.start_offset + len(unit.text) - len(unit.text.lstrip())


def unit_index_at(units: tuple[SourceUnit, ...], position: int) -> int | None:
    """Index of the unit owning ``position``, or ``None`` when out of range."""

    for unit_index, unit in enumerate(units):
        if unit.start_offset <= position < unit.end_offset:
            return unit_index
    return None


def resolvable_anchors(
    text: str,
    scene_anchors: tuple[SourceSceneAnchor, ...] | list[SourceSceneAnchor],
) -> tuple[tuple[SourceSceneAnchor, ...], tuple[str, ...]]:
    """Split anchors into those that define a valid boundary and those that don't.

    Scene anchors come from a model. One that cannot be located as a complete
    unit start after the previous scene defines no boundary at all — but it must
    not destroy the whole source document, so Extract drops it and the preceding
    scene keeps those units. Callers that own their anchors keep using
    ``build_source_document`` directly and still get a hard failure.
    """

    units = source_units(text)
    kept: list[SourceSceneAnchor] = []
    unresolved: list[str] = []
    search_from = 0
    previous_index: int | None = None
    for anchor in scene_anchors:
        try:
            unit_index = _unit_for_opening_quote(
                text,
                units,
                anchor,
                search_from=search_from,
            )
        except ValueError:
            unresolved.append(anchor.id)
            continue
        if previous_index is not None and unit_index <= previous_index:
            unresolved.append(anchor.id)
            continue
        kept.append(anchor)
        previous_index = unit_index
        search_from = units[unit_index].end_offset
    return tuple(kept), tuple(unresolved)


def _unit_for_opening_quote(
    text: str,
    units: tuple[SourceUnit, ...],
    anchor: SourceSceneAnchor,
    *,
    search_from: int,
) -> int:
    position = anchor.start_offset if anchor.start_offset is not None else text.find(anchor.opening_quote, search_from)
    if position < search_from or not text.startswith(anchor.opening_quote, position):
        position = -1
    if position == -1:
        raise ValueError(
            f"scene {anchor.id!r} verbatim opening quote was not found in source"
        )
    unit_index = unit_index_at(units, position)
    if unit_index is None:
        raise ValueError(f"scene {anchor.id!r} opening quote is outside source units")
    unit = units[unit_index]
    if position != _semantic_start(unit):
        raise ValueError(
            f"scene {anchor.id!r} opening quote creates a mid-sentence boundary"
        )
    if anchor.opening_quote != unit.text.strip():
        raise ValueError(
            f"scene {anchor.id!r} anchor must be the complete opening sentence"
        )
    return unit_index


def build_source_document(
    text: str,
    scene_anchors: list[SourceSceneAnchor] | tuple[SourceSceneAnchor, ...],
    *,
    first_ordinal: int = 1,
) -> SourceDocument:
    """Build exact sentence units and contiguous primary scene ownership."""

    if not text:
        raise ValueError("source text cannot be empty")
    if not scene_anchors:
        raise ValueError("at least one source scene anchor is required")

    units = source_units(text, first_ordinal=first_ordinal)
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

    # Front matter ahead of the first anchored scene — title page, byline,
    # epigraph, part or chapter heading — is still source that needs exactly one
    # primary owner, so the opening scene owns it.
    boundary_indexes[0] = 0

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


_QUOTE_SUBSTITUTIONS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)


def _norm_quote_text(s: str) -> str:
    """Normalise smart quotes and dashes the model may have substituted.

    Every substitution is one character for one character: a match position in
    the normalised copy is also a valid offset into the original source. An
    earlier em-dash-to-``--`` expansion drifted each anchor by the number of
    dashes preceding it, which silently moved scene boundaries.
    """

    return s.translate(_QUOTE_SUBSTITUTIONS)


def _fuzzy_find_quote(norm_text: str, norm_quote: str, start: int = 0) -> int:
    """Fuzzy-locate a quote whose exact prefix never matches.

    Anchors candidate windows on individual words of the quote, then scores
    each window with SequenceMatcher. Only a strong match (>0.85) is accepted
    so a wrong-but-similar passage doesn't mis-anchor the scene.
    """

    probe = norm_quote[:60].lower()
    if len(probe) < 20:
        return -1
    text_lower = norm_text.lower()
    words = [w.strip("\"'.,;:!?") for w in probe.split()]
    words = [w for w in words if len(w) >= 4]
    if not words:
        return -1

    seen: set[int] = set()
    best_pos = -1
    best_ratio = 0.85
    for word in words[:6]:
        offset = probe.find(word)
        idx = text_lower.find(word, start)
        hops = 0
        while idx != -1 and hops < 500:
            window_start = idx - offset
            if window_start >= start and window_start not in seen:
                seen.add(window_start)
                window = text_lower[window_start:window_start + len(probe)]
                ratio = SequenceMatcher(None, probe, window).ratio()
                if ratio > best_ratio or (
                    ratio == best_ratio and best_pos != -1 and window_start < best_pos
                ):
                    best_pos = window_start
                    best_ratio = ratio
            hops += 1
            idx = text_lower.find(word, idx + 1)
    return best_pos


def _find_quote_position(text: str, quote: str, start: int = 0) -> int:
    """Locate a scene quote in the novel text at or after ``start``.

    Tries progressively shorter prefixes so minor model transcription errors
    (e.g. a misquoted word at the end) don't cause a miss, then falls back to
    a fuzzy word-anchored search. Searching from ``start`` keeps anchors
    monotonic: a short prefix like "The next morning" can't match an earlier
    occurrence and silently reorder scenes. Returns -1 if nothing matches.
    """

    if not quote:
        return -1

    norm_text = _norm_quote_text(text)
    norm_quote = _norm_quote_text(quote)
    # A model that typed an em dash as "--" needs the doubled form collapsed to
    # match the single-character normalisation above.
    candidates = [norm_quote]
    collapsed = re.sub(r"-{2,}", "-", norm_quote)
    if collapsed != norm_quote:
        candidates.append(collapsed)

    for candidate in candidates:
        position = norm_text.find(candidate, start)
        if position != -1:
            return position
    # A line break typed as a space is still an exact copy: headings, dates
    # and list rows open scenes on lines too short for the fuzzy search below.
    for candidate in candidates:
        spaced = re.compile(r"\s+".join(re.escape(word) for word in candidate.split()))
        if candidate.split() and (match := spaced.search(norm_text, start)):
            return match.start()

    for candidate in candidates:
        for length in (len(candidate), 80, 60, 40, 25):
            if length > len(candidate):
                continue
            position = norm_text.find(candidate[:length], start)
            if position != -1:
                return position

    return _fuzzy_find_quote(norm_text, candidates[-1], start)


def align_scene_anchors(story_bible: StoryBible, text: str) -> tuple[str, ...]:
    """Snap every scene's source anchor onto the source unit that owns it.

    ``source_start_quote`` stays verbatim source text and remains the scene
    boundary anchor, but model output is only an approximation: it truncates
    long sentences and occasionally starts mid-sentence. Replacing each anchor
    with the exact text of its owning unit is what keeps the Story Bible and the
    canonical `SourceDocument` in agreement — both read the same units, so no
    second sentence-splitting heuristic can disagree with the first.

    Returns the IDs of scenes whose anchor could not be placed at all.
    """

    return align_scene_openings(story_bible.scenes, text)


def _locate_openings(
    scenes: list[SceneOpening], text: str, units: tuple[SourceUnit, ...],
) -> list[int | None]:
    """Index of the unit each opening starts, in order; ``None`` when it has none."""
    search_from = 0
    previous_index = -1
    located: list[int | None] = []
    for scene in scenes:
        located.append(None)
        quote = scene.source_start_quote.strip()
        if not quote:
            continue

        position = scene.source_start_offset if scene.source_start_offset is not None else text.find(quote, search_from)
        if scene.source_start_offset is not None and (
            position < search_from or not text.startswith(quote, position)
        ):
            continue
        if position == -1 and scene.source_start_offset is None:
            position = _find_quote_position(text, quote, start=search_from)
        if position == -1:
            continue

        # Searching forward from the previous boundary already guarantees a
        # later position; the index check catches the remaining case where the
        # fuzzy matcher lands inside the unit that boundary already owns.
        unit_index = unit_index_at(units, position)
        if unit_index is None or unit_index <= previous_index:
            continue
        unit = units[unit_index]
        if scene.source_start_offset is not None and (
            position != _semantic_start(unit) or quote != unit.text.strip()
        ):
            continue
        if not unit.text.strip():
            continue

        located[-1] = unit_index
        previous_index = unit_index
        search_from = unit.end_offset
    return located


def align_scene_openings(scenes: Iterable[SceneOpening], text: str) -> tuple[str, ...]:
    """Resolve ordered source openings independently of entity/book metadata."""
    scenes = list(scenes)
    units = source_units(text)
    unresolved: list[str] = []
    for scene, unit_index in zip(scenes, _locate_openings(scenes, text, units)):
        if unit_index is None:
            unresolved.append(scene.id)
        else:
            scene.source_start_quote = units[unit_index].text.strip()
    return tuple(unresolved)


# Below this a window sentence is not evidence of the scene's opening. Unrelated
# English sentences of similar length score roughly 0.3-0.5.
_SETTLE_SIMILARITY = 0.7


def _comparable(value: str) -> str:
    return " ".join(_norm_quote_text(value).split()).casefold()


def _opening_similarity(quote: str, sentence: str) -> float:
    """How well a model's opening quote matches one source sentence.

    A quote that stops early, runs into the next sentence or starts
    mid-sentence still names its sentence, so only the overlap is compared.
    """
    if not quote or not sentence:
        return 0.0
    if quote in sentence:
        return 1.0
    length = min(len(quote), len(sentence))
    if length >= 12:
        quote, sentence = quote[:length], sentence[:length]
    return SequenceMatcher(None, quote, sentence, autojunk=False).ratio()


def settle_scene_openings(
    scenes: Iterable[SceneOpening], text: str,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Place the openings ``align_scene_openings`` cannot, without another model call.

    An unresolved scene can only start between the scenes resolved around it.
    Inside that window a weaker match than the whole-text search accepts is
    safe, so the closest sentence becomes the opening. A quote that starts
    inside the previous scene's opening sentence takes the next sentence, the
    nearest boundary after it. The first scene owns the start of the text.

    Returns each settled scene's exact source sentence, and the scenes that
    have no boundary of their own. Nothing is mutated.
    """
    scenes = list(scenes)
    units = source_units(text)
    located = _locate_openings(scenes, text, units)
    comparable = [_comparable(unit.text) for unit in units]
    settled: dict[str, str] = {}
    unplaced: list[str] = []
    for index, scene in enumerate(scenes):
        if located[index] is not None:
            continue
        if scene.source_start_offset is not None:
            # Recorded provenance is exact or wrong; it is never guessed.
            unplaced.append(scene.id)
            continue
        previous = max((unit for unit in located[:index] if unit is not None), default=-1)
        later = located[index + 1:]
        following = next((unit for unit in later if unit is not None), len(units))
        # Each unresolved scene ahead of the next resolved one needs a sentence too.
        pending = next((offset for offset, unit in enumerate(later) if unit is not None), len(later))
        window = [unit for unit in range(previous + 1, following - pending) if comparable[unit]]
        quote = _comparable(scene.source_start_quote)
        choice = None
        if window:
            score, best = max((_opening_similarity(quote, comparable[unit]), -unit) for unit in window)
            if score >= _SETTLE_SIMILARITY:
                choice = -best
            elif previous == -1:
                choice = window[0]
            elif quote and quote in comparable[previous] and not comparable[previous].startswith(quote):
                choice = window[0]
        if choice is None:
            unplaced.append(scene.id)
            continue
        located[index] = choice
        settled[scene.id] = units[choice].text.strip()
    return settled, tuple(unplaced)


def produce_source_document(
    artifacts: TargetArtifacts,
    text: str,
    story_bible: StoryBible,
    /,
    *,
    part_id: str | None = None,
    first_ordinal: int = 1,
) -> SourceDocument:
    """Build and persist Extract's sole canonical source-text artifact.

    Anchors that define no valid boundary are dropped rather than failing the
    stage: the source text, its units, and complete single-owner coverage are
    the contract here, and one unplaceable scene quote out of twelve is not a
    reason to lose all of it. Extract has no approval checkpoint, so a crash
    here leaves the user with nothing to inspect or correct.
    """

    # A part's source document covers only that part's scenes.
    scenes = [scene for scene in story_bible.scenes
              if part_id is None or scene.part_id == part_id]
    anchors, unresolved = resolvable_anchors(
        text,
        tuple(
            SourceSceneAnchor(
                id=scene.id,
                title=scene.title,
                opening_quote=scene.source_start_quote,
                start_offset=scene.source_start_offset,
            )
            for scene in scenes
        ),
    )
    if not anchors:
        raise ValueError(
            "no Story Bible scene anchor could be located in the source text"
        )
    if unresolved:
        logger.warning(
            "Source scenes folded into the preceding scene, anchor not locatable: %s",
            ", ".join(unresolved),
        )
    document = build_source_document(text, anchors, first_ordinal=first_ordinal)
    artifacts.write_source(document)
    return document
