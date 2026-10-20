"""Provider-free shard algebra for one part's book adaptation.

Adapt writes a book adaptation in source-owned shards. This module splits a
candidate back into those shard drafts, plans scoped repairs from validation
failures, and splices repaired drafts into one renumbered adaptation with a
complete source ledger, or refuses. It never calls a model or writes artifacts.

The draft classes keep their historical names: they are model-facing schemas,
and their names appear in the provider JSON schema (``$defs``), which paid
request hashes cover.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.adaptation import (
    AdaptationLedgerEntry,
    AdaptedBeat,
    BookAdaptation,
    LetteringItem,
)
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.validation import InvariantFailure

MISSING_LEDGER_EXCEPTION = "missing_model_authored_omission_exception"


class _LedgerException(BaseModel):
    """Only source-accounting decisions that cannot be derived from beats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_unit_ids: tuple[str, ...] = Field(min_length=1)
    disposition: Literal[
        "visual_motif",
        "compressed_into",
        "intentionally_omitted",
    ]
    adapted_beat_ids: tuple[str, ...] = ()
    reason: str | None = None
    preserved_function: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_exception(self) -> "_LedgerException":
        if self.disposition in {"compressed_into", "intentionally_omitted"}:
            if not self.reason:
                raise ValueError(f"{self.disposition} requires a reason")
        if self.disposition == "intentionally_omitted" and self.adapted_beat_ids:
            raise ValueError(
                "intentionally_omitted cannot have an adapted-beat destination"
            )
        if self.disposition != "intentionally_omitted" and not self.adapted_beat_ids:
            raise ValueError(
                f"{self.disposition} requires nonempty adapted_beat_ids containing "
                "exact existing beat IDs. A destination described only in reason "
                "or preserved_function (such as 'beat_030 onward') is not a citation."
            )
        return self


class _BookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[AdaptedBeat, ...]
    # ``ledger`` remains accepted internally while tests and failed paid
    # candidates migrate. Production prompts request only compact exceptions;
    # code expands them into the canonical one-entry-per-source-unit ledger.
    ledger: tuple[AdaptationLedgerEntry, ...] = ()
    ledger_exceptions: tuple[_LedgerException, ...] = ()


def dedupe_requirement_citations(draft: _BookDraft) -> _BookDraft:
    """Keep one stable requirement citation per beat; text lives in the Brief."""
    return draft.model_copy(update={"beats": tuple(
        beat.model_copy(update={"brief_requirement_ids": tuple(dict.fromkeys(beat.brief_requirement_ids))})
        for beat in draft.beats
    )})


def _merge_book_drafts(
    drafts: list[_BookDraft],
) -> tuple[_BookDraft, dict[str, int]]:
    """Rebase shard-local identifiers into one consecutive global sequence."""

    external_maps: dict[str, list[str]] = {}
    ordinal = 0
    for part in drafts:
        for beat in part.beats:
            ordinal += 1
            external_maps.setdefault(beat.id, []).append(f"beat_{ordinal:04d}")

    beats: list[AdaptedBeat] = []
    ledger: list[AdaptationLedgerEntry] = []
    beat_to_shard: dict[str, int] = {}
    lettering_number = 0
    for shard_index, draft in enumerate(drafts, 1):
        beat_id_map: dict[str, str] = {}
        for beat in draft.beats:
            beat_id_map[beat.id] = f"beat_{len(beats) + len(beat_id_map) + 1:04d}"
        for beat in draft.beats:
            beat_to_shard[beat_id_map[beat.id]] = shard_index - 1
            lettering = []
            for item in beat.lettering:
                lettering_number += 1
                lettering.append(
                    item.model_copy(update={"id": f"lettering_{lettering_number:04d}"})
                )
            beats.append(
                beat.model_copy(
                    update={
                        "id": beat_id_map[beat.id],
                        "order": len(beats) + 1,
                        "lettering": tuple(lettering),
                    }
                )
            )
        for entry in draft.ledger:
            ledger.append(
                entry.model_copy(
                    update={
                        "adapted_beat_ids": tuple(
                            beat_id_map.get(
                                beat_id,
                                external_maps[beat_id][0]
                                if entry.disposition == "compressed_into" and len(external_maps.get(beat_id, [])) == 1
                                else f"invalid_shard_{shard_index}_{beat_id}",
                            )
                            for beat_id in entry.adapted_beat_ids
                        )
                    }
                )
            )
    return _BookDraft(beats=tuple(beats), ledger=tuple(ledger)), beat_to_shard


def materialize_ledger(
    draft: _BookDraft,
    source_unit_ids: tuple[str, ...],
) -> _BookDraft:
    """Expand compact model decisions into the canonical source ledger."""

    beat_by_id = {beat.id: beat for beat in draft.beats}
    beats_by_source: dict[str, list[str]] = {}
    lettering_by_source: dict[str, tuple[str, str]] = {}
    for beat in draft.beats:
        for source_id in beat.source_unit_ids:
            beats_by_source.setdefault(source_id, []).append(beat.id)
        for item in beat.lettering:
            # SFX is canonical publishable lettering, but the source ledger
            # accounts for its underlying action as depicted. Keeping it out of
            # this map also lets dialogue/caption on the same source unit retain
            # the more specific reader-facing disposition.
            if item.kind == "sfx":
                continue
            for source_id in item.source_unit_ids:
                lettering_by_source.setdefault(source_id, (item.kind, beat.id))

    exception_by_source: dict[str, _LedgerException] = {}
    for exception in draft.ledger_exceptions:
        for source_id in exception.source_unit_ids:
            if source_id in exception_by_source:
                raise ValueError(
                    f"source unit {source_id!r} has duplicate ledger exceptions"
                )
            exception_by_source[source_id] = exception

    ledger: list[AdaptationLedgerEntry] = []
    for source_id in source_unit_ids:
        exception = exception_by_source.get(source_id)
        if exception is not None:
            ledger.append(
                AdaptationLedgerEntry(
                    source_unit_id=source_id,
                    disposition=exception.disposition,
                    adapted_beat_ids=exception.adapted_beat_ids,
                    reason=exception.reason,
                    preserved_function=exception.preserved_function,
                )
            )
            continue

        lettering = lettering_by_source.get(source_id)
        if lettering is not None:
            kind, beat_id = lettering
            ledger.append(
                AdaptationLedgerEntry(
                    source_unit_id=source_id,
                    disposition=kind,
                    adapted_beat_ids=(beat_id,),
                    preserved_function=(f"Realized as canonical {kind} in {beat_id}."),
                )
            )
            continue

        beat_ids = tuple(dict.fromkeys(beats_by_source.get(source_id, ())))
        if beat_ids:
            summaries = "; ".join(beat_by_id[beat_id].summary for beat_id in beat_ids)
            ledger.append(
                AdaptationLedgerEntry(
                    source_unit_id=source_id,
                    disposition="depicted",
                    adapted_beat_ids=beat_ids,
                    preserved_function=f"Depicted through: {summaries}",
                )
            )
            continue

        ledger.append(
            AdaptationLedgerEntry(
                source_unit_id=source_id,
                disposition="intentionally_omitted",
                reason=MISSING_LEDGER_EXCEPTION,
                preserved_function=(
                    "The model omitted this source unit without the required "
                    "explicit exception."
                ),
            )
        )

    return draft.model_copy(
        update={
            "ledger": tuple(ledger),
            "ledger_exceptions": (),
        }
    )


def merge_shard_drafts(
    drafts: list[_BookDraft],
) -> tuple[_BookDraft, dict[str, int]]:
    if len(drafts) == 1:
        return drafts[0], {beat.id: 0 for beat in drafts[0].beats}
    return _merge_book_drafts(drafts)


def _affected_shards(
    failures: Sequence[InvariantFailure],
    *,
    beat_to_shard: Mapping[str, int],
    shard_source_ids: tuple[tuple[str, ...], ...],
) -> tuple[int, ...]:
    source_to_shard = {
        source_id: shard_index
        for shard_index, source_ids in enumerate(shard_source_ids)
        for source_id in source_ids
    }
    affected: set[int] = set()
    for failure in failures:
        affected.update(
            beat_to_shard[artifact_id]
            for artifact_id in failure.artifact_ids
            if artifact_id in beat_to_shard
        )
        affected.update(
            source_to_shard[source_id]
            for source_id in failure.source_unit_ids
            if source_id in source_to_shard
        )
    return tuple(sorted(affected))


def _repair_source_scope(
    source: SourceDocument,
    shard_source_ids: tuple[str, ...],
    failures: Sequence[InvariantFailure],
) -> tuple[str, ...]:
    """Expand cited failures to complete source scenes, not complete shards."""

    shard_set = set(shard_source_ids)
    failed = {
        source_id
        for failure in failures
        for source_id in failure.source_unit_ids
        if source_id in shard_set
    }
    if not failed:
        return shard_source_ids
    scoped = {
        source_id
        for scene in source.scenes
        if failed.intersection(scene.unit_ids(source))
        for source_id in scene.unit_ids(source)
        if source_id in shard_set
    }
    return tuple(source_id for source_id in shard_source_ids if source_id in scoped)


def _closed_repair_scope(
    draft: _BookDraft, source_unit_ids: tuple[str, ...],
    owned_source_unit_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Close a replacement over complete beats and their literal source claims.

    Scene boundaries and beat boundaries need not coincide. Replacing any part
    of a beat removes all of its lettering, so all of that evidence must be in
    the writer's scope too. Repeat for overlapping beats until stable.
    External compression links remain redirectable without rewriting their source.
    """
    wanted = set(source_unit_ids)
    while True:
        touched = [b for b in draft.beats if wanted.intersection(b.source_unit_ids)]
        # A replacement occupies one contiguous interval in authored beat
        # order. Close over intervening beats too; source citation order is not
        # narrative order (a flashback may cite an earlier summary sentence).
        positions = [i for i, b in enumerate(draft.beats) if b in touched]
        if positions:
            touched = list(draft.beats[min(positions):max(positions) + 1])
        touched_ids = {b.id for b in touched}
        expanded = wanted | {
            source_id for beat in touched for source_id in beat.source_unit_ids
        } | {
            source_id for beat in touched for item in beat.lettering
            for source_id in item.source_unit_ids
        } | {
            entry.source_unit_id for entry in draft.ledger
            if entry.disposition in {"depicted", "dialogue", "thought", "caption"}
            and touched_ids.intersection(entry.adapted_beat_ids)
        }
        if expanded == wanted:
            break
        wanted = expanded
    unknown = wanted - set(owned_source_unit_ids)
    if unknown:
        raise ValueError(f"Repair scope crosses unowned source units: {sorted(unknown)}")
    return tuple(source_id for source_id in owned_source_unit_ids if source_id in wanted)


def _subset_draft(
    draft: _BookDraft,
    source_unit_ids: tuple[str, ...],
) -> _BookDraft:
    wanted = set(source_unit_ids)
    beat_ids = {
        beat.id for beat in draft.beats if wanted.intersection(beat.source_unit_ids)
    }
    return _BookDraft(
        beats=tuple(beat for beat in draft.beats if beat.id in beat_ids),
        ledger=tuple(entry for entry in draft.ledger if entry.source_unit_id in wanted),
    )


def _rebase_local_draft(draft: _BookDraft) -> _BookDraft:
    beat_id_map = {
        beat.id: f"beat_{index:04d}" for index, beat in enumerate(draft.beats, 1)
    }
    lettering_number = 0
    beats: list[AdaptedBeat] = []
    for order, beat in enumerate(draft.beats, 1):
        lettering: list[LetteringItem] = []
        for item in beat.lettering:
            lettering_number += 1
            lettering.append(
                item.model_copy(update={"id": f"lettering_{lettering_number:04d}"})
            )
        beats.append(
            beat.model_copy(
                update={
                    "id": beat_id_map[beat.id],
                    "order": order,
                    "lettering": tuple(lettering),
                }
            )
        )
    return _BookDraft(
        beats=tuple(beats),
        ledger=tuple(
            entry.model_copy(
                update={
                    "adapted_beat_ids": tuple(
                        beat_id_map[beat_id]
                        for beat_id in entry.adapted_beat_ids
                    )
                }
            )
            for entry in draft.ledger
        ),
    )


def validate_draft_source_scope(draft: _BookDraft, source_unit_ids: tuple[str, ...]) -> None:
    """Reject copied neighbor citations before caching or splicing a repair.

    Compression may point to an external beat, but its source citation still
    belongs to this repair. Never erase or relabel an out-of-scope citation.
    """
    allowed = set(source_unit_ids)
    claims = [(f"beat {beat.id}", beat.source_unit_ids) for beat in draft.beats]
    claims.extend((f"lettering {item.id}", item.source_unit_ids)
                  for beat in draft.beats for item in beat.lettering)
    claims.extend((f"ledger exception {index}", entry.source_unit_ids)
                  for index, entry in enumerate(draft.ledger_exceptions, 1))
    errors = [f"{owner}: {sorted(set(citations) - allowed)}"
              for owner, citations in claims if set(citations) - allowed]
    if errors:
        raise ValueError("Repair contains out-of-scope literal provenance: " + "; ".join(errors))
    accounted = {source_id for _, citations in claims for source_id in citations}
    accounted.update(entry.source_unit_id for entry in draft.ledger
                     if entry.reason != MISSING_LEDGER_EXCEPTION)
    missing = allowed - accounted
    if missing:
        raise ValueError(
            f"Repair is missing source accounting for {sorted(missing)}. "
            "Preserve the source in a beat or author an explicit ledger exception with a reason."
        )


def _repair_required_requirements(candidate: BookAdaptation, scope: tuple[str, ...]) -> tuple[str, ...]:
    """Retain requirement ownership that would otherwise disappear in a splice."""
    removed, retained = set(), set()
    for beat in candidate.beats:
        owner = removed if set(scope).intersection(beat.source_unit_ids) else retained
        owner.update(beat.brief_requirement_ids)
    return tuple(sorted(removed - retained))


def validate_repair_requirements(draft: _BookDraft, required: tuple[str, ...]) -> None:
    covered = {requirement for beat in draft.beats for requirement in beat.brief_requirement_ids}
    missing = set(required) - covered
    if missing:
        raise ValueError(
            f"Repair dropped required event/character citations: {sorted(missing)}. "
            "Carry each requirement in a source-backed beat and cite its exact approved ID."
        )


def _splice_draft_repairs(
    draft: _BookDraft,
    repairs: list[tuple[_BookDraft, tuple[str, ...]]],
    source_order: Mapping[str, int],
) -> _BookDraft:
    """Resolve a whole repair transaction before rebasing any global IDs.

    Compression may move a claim to another shard's retained or replacement
    beat. Literal evidence remains source-owned. Unknown/deleted destinations
    fail closed; proximity is never evidence for a replacement ledger link.
    """
    owned = tuple(sorted(
        {e.source_unit_id for e in draft.ledger}
        | {u for b in draft.beats for u in b.source_unit_ids}
        | {u for b in draft.beats for i in b.lettering for u in i.source_unit_ids},
        key=lambda u: source_order.get(u, len(source_order)),
    ))
    original_ids = {b.id for b in draft.beats}
    replaced_sources, removed_ids, new_ids = set(), set(), set()
    aliases, insertions, replacement_ledger = {}, {}, []
    for index, (repair, scope) in enumerate(repairs):
        wanted = set(scope)
        missing = set(_closed_repair_scope(draft, scope, owned)) - wanted
        if missing:
            raise ValueError(f"Repair would remove out-of-scope source evidence: {sorted(missing)}")
        if wanted & replaced_sources or wanted - set(owned):
            raise ValueError("Repair scopes overlap or cross unowned source units.")
        replaced_sources.update(wanted)
        positions = [i for i, b in enumerate(draft.beats) if wanted.intersection(b.source_unit_ids)]
        removed = [draft.beats[i] for i in positions]
        removed_ids.update(b.id for b in removed)
        id_map = {b.id: f"repair_{index}_{b.id}" for b in repair.beats}
        if len(id_map) != len(repair.beats):
            raise ValueError("Repair contains duplicate beat IDs.")
        if {e.source_unit_id for e in repair.ledger} != wanted:
            raise ValueError("Repair ledger must account for exactly its source scope.")
        validate_draft_source_scope(repair, scope)
        if set(id_map.values()) & original_ids:
            raise ValueError("Repair namespace collides with an existing beat.")
        new_ids.update(id_map.values())
        scoped_ledger = []
        for entry in repair.ledger:
            external = set(entry.adapted_beat_ids) - set(id_map)
            if external and entry.disposition != "compressed_into":
                raise ValueError("Only compression may target an external repair beat.")
            if external - original_ids:
                raise ValueError(f"Repair cites unknown external beats: {sorted(external - original_ids)}")
            scoped_ledger.append(entry.model_copy(update={"adapted_beat_ids": tuple(
                id_map.get(target, target) for target in entry.adapted_beat_ids
            )}))
        replacement_ledger.extend(scoped_ledger)
        destinations = {e.source_unit_id: e.adapted_beat_ids for e in scoped_ledger}
        for old in removed:
            preserved = next((b for b in repair.beats if b.id == old.id
                              and set(b.source_unit_ids).intersection(old.source_unit_ids)), None)
            targets = ([id_map[preserved.id]] if preserved is not None else
                       [t for u in old.source_unit_ids for t in destinations.get(u, ())])
            if not targets:
                targets = [id_map[b.id] for b in repair.beats
                           if set(old.source_unit_ids).intersection(b.source_unit_ids)]
            aliases[old.id] = tuple(dict.fromkeys(targets))
        if positions:
            insertion = min(positions)
        else:
            first = min((source_order[u] for u in wanted), default=len(source_order))
            insertion = next((i for i, b in enumerate(draft.beats)
                              if min(source_order[u] for u in b.source_unit_ids) > first), len(draft.beats))
        insertions.setdefault(insertion, []).extend(
            b.model_copy(update={"id": id_map[b.id]}) for b in repair.beats
        )

    retained_ids = original_ids - removed_ids
    def resolve(target, trail=()):
        if target in new_ids or target in retained_ids:
            return (target,)
        if target in trail:
            raise ValueError(f"Repair compression contains a cyclic destination: {target}")
        if not aliases.get(target):
            raise ValueError(f"Repair removed referenced beat without a supported destination: {target}")
        return tuple(dict.fromkeys(t for linked in aliases[target] for t in resolve(linked, (*trail, target))))

    beats = []
    for index, beat in enumerate(draft.beats):
        beats.extend(insertions.get(index, ()))
        if beat.id not in removed_ids:
            beats.append(beat)
    beats.extend(insertions.get(len(draft.beats), ()))
    ledger = [e for e in draft.ledger if e.source_unit_id not in replaced_sources] + replacement_ledger
    ledger = [e.model_copy(update={"adapted_beat_ids": tuple(dict.fromkeys(
        resolved for target in e.adapted_beat_ids for resolved in resolve(target)
    ))}) for e in ledger]
    ledger.sort(key=lambda e: source_order.get(e.source_unit_id, len(source_order)))
    return _rebase_local_draft(_BookDraft(beats=tuple(beats), ledger=tuple(ledger)))


def partition_candidate(candidate, shards) -> list[_BookDraft]:
    """Keep reviewed global IDs in repair inputs and enforce shard ownership."""
    source_owner = {u: index for index, ids in enumerate(shards) for u in ids}
    beats = [[] for _ in shards]
    owners = []
    for beat in candidate.beats:
        sources = set(beat.source_unit_ids) | {u for i in beat.lettering for u in i.source_unit_ids}
        ownership = {source_owner.get(u) for u in sources}
        if len(ownership) != 1 or None in ownership:
            raise ValueError("Reviewed candidate crosses source ownership; repair cannot safely resume.")
        owner = ownership.pop()
        owners.append(owner)
        beats[owner].append(beat)
    if owners != sorted(owners):
        raise ValueError("Reviewed candidate crosses shard order; repair cannot safely resume.")
    drafts = []
    for index, ids in enumerate(shards):
        local_ids = {b.id for b in beats[index]}
        ledger = tuple(e for e in candidate.ledger if e.source_unit_id in ids)
        if any(set(e.adapted_beat_ids) - local_ids and e.disposition != "compressed_into" for e in ledger):
            raise ValueError("Reviewed ledger crosses shard ownership; repair cannot safely resume.")
        drafts.append(_BookDraft(beats=tuple(beats[index]), ledger=ledger))
    return drafts


def _repair_boundary_context(candidate, scope):
    """Expose retained events immediately outside the replacement interval."""
    wanted = set(scope)
    positions = [i for i, beat in enumerate(candidate.beats) if wanted.intersection(beat.source_unit_ids)]
    if not positions:
        return {"before": [], "after": []}
    first, last = min(positions), max(positions)
    def view(beats):
        return [{"id": b.id, "source_unit_ids": b.source_unit_ids, "summary": b.summary,
                 "lettering": [i.model_dump(mode="json") for i in b.lettering]} for b in beats]
    return {
        "before": view(candidate.beats[max(0, first - 3):first]),
        "after": view(candidate.beats[last + 1:last + 4]),
    }


@dataclass(frozen=True)
class ShardRepair:
    """One shard's scoped rewrite and what it must keep."""

    shard_index: int
    # Closed over whole beats, their literal claims and authored beat order.
    scope: tuple[str, ...]
    # Brief requirements only the replaced beats carried.
    required_requirement_ids: tuple[str, ...]
    # The shard's current beats and ledger within scope.
    current: _BookDraft
    # Retained beats immediately before and after the replaced interval.
    neighbors: dict


@dataclass(frozen=True)
class RepairPlan:
    shards: tuple[tuple[str, ...], ...]
    beat_to_shard: Mapping[str, int]
    repairs: tuple[ShardRepair, ...]

    @property
    def affected(self) -> tuple[int, ...]:
        return tuple(repair.shard_index for repair in self.repairs)


def plan_repairs(
    source: SourceDocument,
    candidate: BookAdaptation,
    shards: Sequence[tuple[str, ...]],
    failures: Sequence[InvariantFailure],
) -> RepairPlan:
    """Choose the shards to rewrite and the source scope each rewrite owns.

    Raises ValueError when the candidate crosses shard ownership.
    """
    drafts = partition_candidate(candidate, shards)
    _, beat_to_shard = merge_shard_drafts(drafts)
    affected = _affected_shards(failures, beat_to_shard=beat_to_shard, shard_source_ids=tuple(shards))
    repairs = []
    for index in affected:
        scope = _closed_repair_scope(
            drafts[index], _repair_source_scope(source, shards[index], failures), shards[index],
        )
        repairs.append(ShardRepair(
            shard_index=index,
            scope=scope,
            required_requirement_ids=_repair_required_requirements(candidate, scope),
            current=_subset_draft(drafts[index], scope),
            neighbors=_repair_boundary_context(candidate, scope),
        ))
    return RepairPlan(shards=tuple(shards), beat_to_shard=beat_to_shard, repairs=tuple(repairs))


def splice_repairs(
    source: SourceDocument,
    candidate: BookAdaptation,
    plan: RepairPlan,
    drafts: Sequence[_BookDraft],
) -> BookAdaptation:
    """Replace each planned scope with its repaired draft, in one transaction.

    ``drafts`` pairs with ``plan.repairs`` and holds the writer's compact
    output; the source ledger is materialized here. Raises ValueError when a
    repair crosses its scope or the result crosses shard ownership.
    """
    scoped = [
        (dedupe_requirement_citations(materialize_ledger(draft, repair.scope)), repair.scope)
        for draft, repair in zip(drafts, plan.repairs, strict=True)
    ]
    combined = _splice_draft_repairs(
        _BookDraft(beats=candidate.beats, ledger=candidate.ledger),
        scoped, {unit.id: unit.ordinal for unit in source.units},
    )
    repaired = BookAdaptation.model_validate({
        **candidate.model_dump(mode="json"), "content_sha256": "",
        "beats": combined.beats, "ledger": combined.ledger,
    })
    partition_candidate(repaired, plan.shards)
    return repaired
