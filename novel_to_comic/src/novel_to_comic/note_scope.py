"""Carry one author note to every page it touches, at the layer that owns it.

The change checker reads a note against one page and may name a fact that
reaches further: a line of the script, a story moment, or a look that holds
over a run of pages. This module turns that typed claim into exact page lists
and into amended canonical artifacts. The model names the fact; code finds
the pages. Nothing here calls a model, reads files or spends.

Amendments edit the accepted adaptation in place (``AdaptationAmendment``)
instead of re-running Adapt, so only pages that cite a changed beat, or whose
panels change, get a new ComicPage revision and go out of date.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.adaptation import (
    AdaptationAmendment,
    AdaptedBeat,
    BookAdaptation,
    LetteringItem,
)
from novel_to_comic.models.page import (
    ApprovedVisualReferenceInventory,
    BookPlan,
    ComicPage,
    PlannedPageRevision,
)
from novel_to_comic.models.validation import InvariantFailure


class NoteScopeError(ValueError):
    """The note can't be carried as stated against the current artifacts."""


class LineClaim(BaseModel):
    """Change the wording or speaker of one canonical lettering line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["line"] = "line"
    lettering_item_id: str = Field(min_length=1)
    text: str | None = Field(default=None, max_length=2000)
    speaker_entity_id: str | None = None


class LookClaim(BaseModel):
    """A look or place fact that holds from one page over a run of pages.

    ``state_id`` reuses an existing look; ``look_label`` with ``look_anchor``
    adds one. With neither, the fact already holds in the entity's current
    look and only artwork that breaks it needs a correction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["look"] = "look"
    entity_id: str = Field(min_length=1)
    fact: str = Field(min_length=1, max_length=600)
    start_page: int = Field(ge=1)
    end_page: int | None = Field(default=None, ge=1)
    state_id: str | None = None
    look_label: str | None = Field(default=None, max_length=80)
    look_anchor: str | None = Field(default=None, max_length=1200)

    @property
    def adds_look(self) -> bool:
        return self.state_id is None and bool((self.look_label or "").strip() and (self.look_anchor or "").strip())

    @property
    def changes_look(self) -> bool:
        return self.state_id is not None or self.adds_look


class BeatClaim(BaseModel):
    """A story moment that is missing or unclear in the cited beats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["beat"] = "beat"
    beat_ids: tuple[str, ...] = Field(min_length=1, max_length=6)
    note: str = Field(min_length=1, max_length=1000)


NoteClaim = Annotated[LineClaim | LookClaim | BeatClaim, Field(discriminator="kind")]


class ScopedPage(BaseModel):
    """One page the change touches, and why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    panels: tuple[int, ...] = ()
    drawn: bool = False
    reason: Literal["line", "beat", "look", "shares_beat"]


class NoteScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pages: tuple[ScopedPage, ...]
    beat_ids: tuple[str, ...] = ()
    end_page: int | None = None
    from_state_id: str | None = None


def _beat_of_item(adaptation: BookAdaptation, item_id: str) -> AdaptedBeat:
    for beat in adaptation.beats:
        if any(item.id == item_id for item in beat.lettering):
            return beat
    raise NoteScopeError(f"Line {item_id!r} is not in the current script.")


def _pages_citing(pages: Sequence[ComicPage], beat_ids) -> list[ComicPage]:
    wanted = set(beat_ids)
    return [page for page in pages if wanted & set(page.cited_beat_ids)]


def line_scope(adaptation: BookAdaptation, pages: Sequence[ComicPage], claim: LineClaim,
               drawn: frozenset[int] = frozenset()) -> NoteScope:
    beat = _beat_of_item(adaptation, claim.lettering_item_id)
    scoped = []
    for page in _pages_citing(pages, (beat.id,)):
        panels = tuple(content.order for content in page.content
                       if any(item.id == claim.lettering_item_id for item in content.lettering))
        scoped.append(ScopedPage(page_number=page.page_number, panels=panels, drawn=page.page_number in drawn,
                                 reason="line" if panels else "shares_beat"))
    return NoteScope(pages=tuple(scoped), beat_ids=(beat.id,))


def beat_scope(adaptation: BookAdaptation, pages: Sequence[ComicPage], claim: BeatClaim,
               drawn: frozenset[int] = frozenset()) -> NoteScope:
    known = {beat.id for beat in adaptation.beats}
    unknown = [beat_id for beat_id in claim.beat_ids if beat_id not in known]
    if unknown:
        raise NoteScopeError("These story beats are not in the current script: " + ", ".join(unknown))
    scoped = []
    for page in _pages_citing(pages, claim.beat_ids):
        panels = tuple(content.order for content in page.content if set(content.beat_ids) & set(claim.beat_ids))
        scoped.append(ScopedPage(page_number=page.page_number, panels=panels, drawn=page.page_number in drawn,
                                 reason="beat"))
    return NoteScope(pages=tuple(scoped), beat_ids=claim.beat_ids)


def _next_change_page(adaptation: BookAdaptation, pages: Sequence[ComicPage], entity_id: str,
                      start_page: int) -> int | None:
    """The first page after ``start_page`` where the script changes this entity's look."""

    changing = {beat.id for beat in adaptation.beats
                for change in beat.appearance_changes if change.entity_id == entity_id}
    for page in pages:
        if page.page_number > start_page and changing & set(page.cited_beat_ids):
            return page.page_number
    return None


def look_scope(adaptation: BookAdaptation, pages: Sequence[ComicPage], claim: LookClaim,
               inventory: ApprovedVisualReferenceInventory,
               drawn: frozenset[int] = frozenset()) -> NoteScope:
    """Every panel from ``start_page`` that shows the entity in the look the fact replaces.

    The run ends at ``end_page``, or before the next page where the script
    itself changes this entity's look. Panels bound to another look on
    purpose (a flashback, a disguise) are left out.
    """

    if claim.entity_id not in {reference.entity_id for reference in inventory.references}:
        raise NoteScopeError(f"{claim.entity_id!r} is not in the Story Bible.")
    if claim.start_page > len(pages):
        raise NoteScopeError(f"Page {claim.start_page} is not in the page plan.")
    end = claim.end_page
    if end is None:
        following = _next_change_page(adaptation, pages, claim.entity_id, claim.start_page)
        end = (following - 1) if following is not None else len(pages)
    end = min(end, len(pages))
    if end < claim.start_page:
        raise NoteScopeError("The last page comes before the first page.")
    in_run = [page for page in pages if claim.start_page <= page.page_number <= end]
    showing = [(page, content) for page in in_run for content in page.content
               if claim.entity_id in content.entity_ids]
    if not showing:
        raise NoteScopeError("Nobody draws this character or place on those pages.")
    first_page, first = showing[0]
    from_state = first.appearance_states.get(claim.entity_id)
    if claim.state_id is not None and from_state == claim.state_id:
        raise NoteScopeError("Those pages already use that look.")
    panels: dict[int, list[int]] = {}
    for page, content in showing:
        if content.appearance_states.get(claim.entity_id) == from_state:
            panels.setdefault(page.page_number, []).append(content.order)
    scoped = [ScopedPage(page_number=number, panels=tuple(orders), drawn=number in drawn, reason="look")
              for number, orders in panels.items()]
    return NoteScope(pages=tuple(scoped), beat_ids=(_first_beat_showing(first_page, claim.entity_id),),
                     end_page=end, from_state_id=from_state)


def _first_beat_showing(page: ComicPage, entity_id: str) -> str:
    for content in sorted(page.content, key=lambda item: item.order):
        if entity_id in content.entity_ids:
            return content.beat_ids[0]
    raise NoteScopeError("The first page doesn't show this character or place.")


def amended(adaptation: BookAdaptation, change_id: str, beats: Mapping[str, AdaptedBeat]) -> BookAdaptation:
    """A new revision with ``beats`` replaced and the amendment recorded."""

    if not beats:
        raise NoteScopeError("The change doesn't alter any beat.")
    unknown = set(beats) - {beat.id for beat in adaptation.beats}
    if unknown:
        raise NoteScopeError("Unknown beats: " + ", ".join(sorted(unknown)))
    payload = adaptation.model_dump(mode="json", exclude={"content_sha256"})
    payload["revision"] = adaptation.revision + 1
    payload["beats"] = [beats.get(beat.id, beat).model_dump(mode="json") for beat in adaptation.beats]
    payload["amendments"] = [
        *(item.model_dump(mode="json") for item in adaptation.amendments),
        AdaptationAmendment(change_id=change_id, from_revision=adaptation.revision,
                            from_sha256=adaptation.content_sha256,
                            changed_beat_ids=tuple(beats)).model_dump(mode="json"),
    ]
    return BookAdaptation.model_validate(payload)


def repinned(page: ComicPage, adaptation: BookAdaptation, content_updates: Mapping[int, dict] | None = None,
             reservation_updates: Mapping[str, dict] | None = None) -> ComicPage:
    """The next revision of ``page``, pinned to ``adaptation``, with panel fields replaced."""

    payload = page.model_dump(mode="json", exclude={"content_sha256"})
    payload["revision"] = page.revision + 1
    payload["adaptation_revision"] = adaptation.revision
    payload["adaptation_sha256"] = adaptation.content_sha256
    for content in payload["content"]:
        content.update((content_updates or {}).get(content["order"], {}))
    if payload.get("lettering_reservations") is not None:
        for reservation in payload["lettering_reservations"]:
            reservation.update((reservation_updates or {}).get(reservation["lettering_item_id"], {}))
    return ComicPage.model_validate(payload)


def next_plan(plan: BookPlan, adaptation: BookAdaptation, revised: Mapping[int, ComicPage]) -> BookPlan:
    payload = plan.model_dump(mode="json", exclude={"content_sha256"})
    payload["revision"] = plan.revision + 1
    payload["adaptation_revision"] = adaptation.revision
    payload["adaptation_sha256"] = adaptation.content_sha256
    payload["pages"] = [
        PlannedPageRevision(page_number=number, revision=revised[number].revision,
                            content_sha256=revised[number].content_sha256).model_dump(mode="json")
        if (number := entry["page_number"]) in revised else entry
        for entry in payload["pages"]
    ]
    return BookPlan.model_validate(payload)


def line_amendment(adaptation: BookAdaptation, pages: Sequence[ComicPage], claim: LineClaim,
                   inventory: ApprovedVisualReferenceInventory, change_id: str,
                   ) -> tuple[BookAdaptation, dict[int, ComicPage]]:
    """Rewrite one line's wording or speaker in the script and on its page.

    A typed edit: no model writes the new line. A changed speaker keeps a
    balloon tail only when the new speaker is drawn in that panel.
    """

    beat = _beat_of_item(adaptation, claim.lettering_item_id)
    item = next(item for item in beat.lettering if item.id == claim.lettering_item_id)
    changes: dict = {}
    if claim.text is not None and claim.text.strip() and claim.text.strip() != item.text:
        changes["text"] = claim.text.strip()
    if claim.speaker_entity_id is not None and claim.speaker_entity_id != item.speaker_entity_id:
        if item.kind not in ("dialogue", "thought"):
            raise NoteScopeError("Only dialogue and thoughts have a speaker.")
        labels = {reference.entity_id: reference.label for reference in inventory.references
                  if reference.kind == "character"}
        if claim.speaker_entity_id not in labels:
            raise NoteScopeError(f"{claim.speaker_entity_id!r} is not a character in the Story Bible.")
        changes["speaker_entity_id"] = claim.speaker_entity_id
        changes["speaker"] = labels[claim.speaker_entity_id] or claim.speaker_entity_id
    if not changes:
        raise NoteScopeError("The line already reads that way.")
    new_item = item.model_copy(update=changes)
    LetteringItem.model_validate(new_item.model_dump())
    new_beat = beat.model_copy(update={
        "lettering": tuple(new_item if candidate.id == item.id else candidate for candidate in beat.lettering),
    })
    revised_adaptation = amended(adaptation, change_id, {beat.id: new_beat})
    revised: dict[int, ComicPage] = {}
    for page in _pages_citing(pages, (beat.id,)):
        content_updates: dict[int, dict] = {}
        reservation_updates: dict[str, dict] = {}
        for content in page.content:
            if not any(candidate.id == item.id for candidate in content.lettering):
                continue
            content_updates[content.order] = {"lettering": [
                (new_item if candidate.id == item.id else candidate).model_dump(mode="json")
                for candidate in content.lettering
            ]}
            if "speaker_entity_id" in changes:
                visible = (changes["speaker_entity_id"] in content.entity_ids
                           and new_item.delivery == "onscreen")
                reservation_updates[item.id] = (
                    {"speaker_entity_id": changes["speaker_entity_id"]} if visible
                    else {"speaker_entity_id": None, "tail_target": None}
                )
        revised[page.page_number] = repinned(page, revised_adaptation, content_updates, reservation_updates)
    return revised_adaptation, revised


def look_amendment(pages: Sequence[ComicPage], claim: LookClaim, scope: NoteScope, state_id: str,
                   rebind: frozenset[int]) -> dict[int, ComicPage]:
    """Bind the chosen pages' panels to the look; the script is unchanged.

    Plan treats an explicit look citation as authoritative, so pages in the
    run that aren't chosen keep their panels: their art already honours the
    fact. Where the look begins is recorded in the Story Bible's timeline,
    which a later Adapt reads.
    """

    by_number = {page.page_number: page for page in pages}
    revised: dict[int, ComicPage] = {}
    for scoped in scope.pages:
        if scoped.page_number not in rebind:
            continue
        page = by_number[scoped.page_number]
        payload = page.model_dump(mode="json", exclude={"content_sha256"})
        payload["revision"] = page.revision + 1
        for content in payload["content"]:
            if content["order"] in scoped.panels:
                content["appearance_states"] = {**content["appearance_states"], claim.entity_id: state_id}
        revised[page.page_number] = ComicPage.model_validate(payload)
    if not revised:
        raise NoteScopeError("Choose at least one page to change.")
    return revised


def beat_amendment(adaptation: BookAdaptation, revisions: Sequence[AdaptedBeat], change_id: str) -> BookAdaptation:
    """Splice revised beats into the script, keeping ids, order and source accounting."""

    current = {beat.id: beat for beat in adaptation.beats}
    replaced: dict[str, AdaptedBeat] = {}
    for revision in revisions:
        beat = current.get(revision.id)
        if beat is None:
            raise NoteScopeError(f"Beat {revision.id!r} is not in the current script.")
        if revision.source_unit_ids != beat.source_unit_ids or revision.order != beat.order:
            raise NoteScopeError("A revised beat must keep its place and its source passages.")
        if revision != beat:
            replaced[beat.id] = revision
    return amended(adaptation, change_id, replaced)


def lettering_after_revision(pages: Sequence[ComicPage], before: BookAdaptation, after: BookAdaptation,
                             beat_ids: Sequence[str]) -> dict[int, tuple[str, ...]]:
    """Each affected page's lines once ``beat_ids`` are revised.

    Kept lines stay on their page. A revised beat's new lines go to the last
    page that carries the beat, in the beat's order; dropped lines leave.
    """

    changed = set(beat_ids)
    old = {beat.id: beat for beat in before.beats}
    new = {beat.id: beat for beat in after.beats}
    placed = {item.id: page.page_number for page in pages for content in page.content for item in content.lettering}
    last_page = {beat_id: max(page.page_number for page in pages if beat_id in page.cited_beat_ids)
                 for beat_id in changed}
    result: dict[int, tuple[str, ...]] = {}
    for page in pages:
        if not changed & set(page.cited_beat_ids):
            continue
        ids: list[str] = []
        for beat_id in page.cited_beat_ids:
            if beat_id not in changed:
                ids.extend(item.id for item in old[beat_id].lettering if placed.get(item.id) == page.page_number)
                continue
            for item in new[beat_id].lettering:
                home = placed.get(item.id, last_page[beat_id])
                if home == page.page_number:
                    ids.append(item.id)
        result[page.page_number] = tuple(ids)
    return result


def new_failures(before: Sequence[InvariantFailure], after: Sequence[InvariantFailure]) -> tuple[InvariantFailure, ...]:
    """Failures the change introduced; ones the book already had don't block it."""

    known = {failure.id for failure in before}
    return tuple(failure for failure in after if failure.id not in known)


__all__ = [
    "BeatClaim",
    "LineClaim",
    "LookClaim",
    "NoteClaim",
    "NoteScope",
    "NoteScopeError",
    "ScopedPage",
    "amended",
    "beat_amendment",
    "beat_scope",
    "line_amendment",
    "line_scope",
    "look_amendment",
    "look_scope",
    "new_failures",
    "next_plan",
    "repinned",
]
