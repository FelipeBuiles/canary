"""Appearance-state chronology across the ordered comic pages.

Adapt decides on which beat an entity changes into which appearance state.
Plan validates its pages against that chronology and Finish checks it again
before export; both use this one implementation so a plan Plan accepts is never
one Finish rejects.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from novel_to_comic.models.adaptation import BookAdaptation
from novel_to_comic.models.page import ComicPage

CODE = "cross_page_appearance_state"


@dataclass(frozen=True)
class ChronologyFinding:
    page_number: int
    owner_stage: str
    message: str
    artifact_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    #: Plan-owned citation findings only: the content, entity, the state the
    #: story has reached, and the cited states it has not reached yet.
    content_id: str | None = None
    entity_id: str | None = None
    expected_state_id: str | None = None
    not_yet_activated: tuple[str, ...] = ()


def final_beat_carriers(pages: Iterable[Any]) -> dict[str, tuple[int, int]]:
    """(page number, panel order) of the last panel carrying each beat.

    A beat's appearance change is its outcome ("Prospero falls dead"). When
    Plan splits one beat across several panels, the change takes effect on the
    beat's last panel; the panels before it show the moments leading up to it
    and keep the entity's prior state unless they cite the new one explicitly.
    Works for Plan drafts and canonical pages alike.
    """

    final: dict[str, tuple[int, int]] = {}
    for page in pages:
        for content in page.content:
            key = (page.page_number, content.order)
            for beat_id in content.beat_ids:
                if key > final.get(beat_id, (-1, -1)):
                    final[beat_id] = key
    return final


def _visible_entities(content: Any) -> set[str]:
    states = content.appearance_states
    bound = states.keys() if isinstance(states, dict) else (b.entity_id for b in states)
    return {*content.entity_ids, *bound}


def change_carriers(
    pages: Iterable[Any],
    beats: dict[str, Any],
    visible: Callable[[Any], set[str]] = _visible_entities,
) -> dict[tuple[str, str], tuple[int, int]]:
    """(page number, panel order) where each (beat, entity) change takes effect.

    A change lands on the last panel of its beat that shows the entity, so a
    split beat ending on a reaction shot of someone else does not drag the
    changed entity into that shot. Only when no panel of the beat shows the
    entity does it fall back to the beat's last panel (``final_beat_carriers``),
    where the change must then be depicted.
    """

    pages = tuple(pages)
    final = final_beat_carriers(pages)
    shown: dict[tuple[str, str], tuple[int, int]] = {}
    for page in pages:
        for content in page.content:
            seen = visible(content)
            for beat_id in content.beat_ids:
                beat = beats.get(beat_id)
                for change in beat.appearance_changes if beat is not None else ():
                    if change.entity_id in seen:
                        shown[(beat_id, change.entity_id)] = (page.page_number, content.order)
    return {
        (beat_id, change.entity_id): shown.get((beat_id, change.entity_id), position)
        for beat_id, position in final.items() if beat_id in beats
        for change in beats[beat_id].appearance_changes
    }


def first_activation(adaptation: BookAdaptation) -> dict[tuple[str, str], str]:
    """The beat that first moves each entity into each state."""

    first: dict[tuple[str, str], str] = {}
    for beat in adaptation.beats:
        for change in beat.appearance_changes:
            first.setdefault((change.entity_id, change.to_state_id), beat.id)
    return first


def appearance_chronology(
    adaptation: BookAdaptation,
    pages: Iterable[ComicPage],
) -> dict[int, list[ChronologyFinding]]:
    """Check explicit state chronology in reading order."""

    pages = tuple(pages)
    beats = {beat.id: beat for beat in adaptation.beats}
    carriers = change_carriers(pages, beats)
    active: dict[str, str] = {}
    activated: dict[str, set[str]] = defaultdict(set)
    findings: dict[int, list[ChronologyFinding]] = defaultdict(list)
    for page in pages:
        for content in page.content:
            position = (page.page_number, content.order)
            # States this panel may cite early: it depicts the beat that
            # produces them, so it may show the change already under way.
            carried = {
                (change.entity_id, change.to_state_id)
                for beat_id in content.beat_ids if beat_id in beats
                for change in beats[beat_id].appearance_changes
            }
            for beat_id in content.beat_ids:
                beat = beats.get(beat_id)
                if beat is None:
                    continue
                # Adjacent content items may decompose one adapted beat into
                # several visual moments. Each change takes effect once, on
                # its carrier (see ``change_carriers``).
                for change in beat.appearance_changes:
                    if carriers.get((beat.id, change.entity_id)) != position:
                        continue
                    current = active.get(change.entity_id)
                    if (
                        change.from_state_id is not None
                        and current != change.from_state_id
                    ):
                        findings[page.page_number].append(ChronologyFinding(
                            page_number=page.page_number,
                            owner_stage="adapt",
                            message="Appearance-state chronology is inconsistent.",
                            artifact_ids=(beat.id, change.entity_id, change.to_state_id),
                            evidence=(
                                f"Expected prior state {change.from_state_id!r}; "
                                f"found {current!r}.",
                            ),
                        ))
                    active[change.entity_id] = change.to_state_id
                    activated[change.entity_id].add(change.to_state_id)
            for entity_id in content.entity_ids:
                expected = active.get(entity_id)
                cited = ([content.appearance_states[entity_id]]
                         if entity_id in content.appearance_states else [])
                not_yet_activated = [
                    state_id
                    for state_id in cited
                    if state_id not in activated.get(entity_id, set())
                    and (entity_id, state_id) not in carried
                ]
                # A page may explicitly cite an earlier state for a timeline
                # or composite image. The invariant is that the state has
                # been activated and that a changed entity is not left
                # without any page-scoped state citation.
                if expected is not None and (not cited or not_yet_activated):
                    evidence = (
                        f"Active state for {entity_id!r} is {expected!r}; "
                        f"page content cites {cited!r}."
                    )
                    if not_yet_activated:
                        evidence = (
                            f"Page content cites states not yet activated for "
                            f"{entity_id!r}: {not_yet_activated!r}."
                        )
                    findings[page.page_number].append(ChronologyFinding(
                        page_number=page.page_number,
                        owner_stage="plan",
                        message="Page-scoped appearance state is stale across pages.",
                        artifact_ids=(content.id, entity_id, expected, *cited),
                        evidence=(evidence,),
                        content_id=content.id,
                        entity_id=entity_id,
                        expected_state_id=expected,
                        not_yet_activated=tuple(not_yet_activated),
                    ))
    return findings
