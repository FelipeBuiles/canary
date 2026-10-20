from __future__ import annotations

import pytest

from novel_to_comic.adaptation_shards import (
    _BookDraft,
    _closed_repair_scope,
    _repair_required_requirements,
    _splice_draft_repairs,
    materialize_ledger,
    merge_shard_drafts,
    partition_candidate,
    plan_repairs,
    splice_repairs,
)
from novel_to_comic.models.adaptation import AdaptationLedgerEntry, BookAdaptation
from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
from novel_to_comic.models.validation import InvariantFailure

from .test_book_adaptation import _book_adaptation


def _six_unit_source() -> SourceDocument:
    texts = [f"Event {n} happens. " for n in range(1, 7)]
    units, offset = [], 0
    for n, text in enumerate(texts, 1):
        units.append(SourceUnit(id=f"source_{n:06d}", ordinal=n, start_offset=offset,
                                end_offset=offset + len(text), text=text))
        offset += len(text)
    scenes = [("scene_001", 1, 3), ("scene_002", 4, 5), ("scene_003", 6, 6)]
    return SourceDocument(text="".join(texts), units=units, scenes=[
        SourceScene(id=scene_id, title=scene_id, first_unit_id=f"source_{first:06d}",
                    last_unit_id=f"source_{last:06d}")
        for scene_id, first, last in scenes
    ])


_SHARDS = (
    ("source_000001", "source_000002", "source_000003"),
    ("source_000004", "source_000005", "source_000006"),
)


def _six_beat_candidate() -> BookAdaptation:
    template = _book_adaptation().beats[0].model_copy(update={"lettering": ()})
    beats = tuple(template.model_copy(update={
        "id": f"beat_{n:04d}", "order": n, "summary": f"Event {n}",
        "source_unit_ids": (f"source_{n:06d}",),
    }) for n in range(1, 7))
    ledger = materialize_ledger(_BookDraft(beats=beats), tuple(u for shard in _SHARDS for u in shard)).ledger
    return BookAdaptation.model_validate({
        **_book_adaptation().model_dump(mode="json"), "content_sha256": "",
        "beats": beats, "ledger": ledger,
    })


def _failure(*source_unit_ids: str) -> InvariantFailure:
    return InvariantFailure(id=f"failure_{'_'.join(source_unit_ids)}", owner_stage="adapt",
                            code="missing_context", message="Context is missing.",
                            source_unit_ids=source_unit_ids, evidence=("The cause is absent.",))


def test_plan_rewrites_the_failing_scene_not_the_whole_shard():
    plan = plan_repairs(_six_unit_source(), _six_beat_candidate(), _SHARDS, (_failure("source_000005"),))

    assert plan.affected == (1,)
    [repair] = plan.repairs
    assert repair.scope == ("source_000004", "source_000005")
    assert [beat.id for beat in repair.current.beats] == ["beat_0004", "beat_0005"]
    assert [beat["id"] for beat in repair.neighbors["before"]] == ["beat_0001", "beat_0002", "beat_0003"]
    assert [beat["id"] for beat in repair.neighbors["after"]] == ["beat_0006"]
    assert plan.beat_to_shard["beat_0002"] == 0
    assert plan.beat_to_shard["beat_0005"] == 1


def test_plan_without_failures_rewrites_nothing():
    plan = plan_repairs(_six_unit_source(), _six_beat_candidate(), _SHARDS, ())
    assert plan.repairs == ()
    assert plan.affected == ()


def test_splicing_unchanged_repairs_returns_the_same_adaptation():
    source, candidate = _six_unit_source(), _six_beat_candidate()
    plan = plan_repairs(source, candidate, _SHARDS, (_failure("source_000002"), _failure("source_000006")))
    assert plan.affected == (0, 1)

    unchanged = [_BookDraft(beats=repair.current.beats) for repair in plan.repairs]
    spliced = splice_repairs(source, candidate, plan, unchanged)

    assert spliced.beats == candidate.beats
    assert spliced.ledger == candidate.ledger


def test_splice_replaces_only_the_planned_scope():
    source, candidate = _six_unit_source(), _six_beat_candidate()
    plan = plan_repairs(source, candidate, _SHARDS, (_failure("source_000005"),))
    rewritten = tuple(beat.model_copy(update={"summary": f"Rewritten {beat.summary}"})
                      for beat in plan.repairs[0].current.beats)

    spliced = splice_repairs(source, candidate, plan, [_BookDraft(beats=rewritten)])

    assert [beat.summary for beat in spliced.beats] == [
        "Event 1", "Event 2", "Event 3", "Rewritten Event 4", "Rewritten Event 5", "Event 6",
    ]
    assert [beat.id for beat in spliced.beats] == [f"beat_{n:04d}" for n in range(1, 7)]
    assert [entry.source_unit_id for entry in spliced.ledger] == [u for shard in _SHARDS for u in shard]


def test_splice_refuses_a_repair_that_cites_source_outside_its_scope():
    source, candidate = _six_unit_source(), _six_beat_candidate()
    plan = plan_repairs(source, candidate, _SHARDS, (_failure("source_000005"),))
    leaked = plan.repairs[0].current.beats[0].model_copy(
        update={"source_unit_ids": ("source_000004", "source_000003")},
    )

    with pytest.raises(ValueError, match="out-of-scope literal provenance"):
        splice_repairs(source, candidate, plan, [_BookDraft(beats=(leaked, plan.repairs[0].current.beats[1]))])


def test_plan_refuses_a_candidate_that_crosses_shard_ownership():
    candidate = _six_beat_candidate()
    straddling = candidate.beats[2].model_copy(update={"source_unit_ids": ("source_000003", "source_000004")})
    candidate = candidate.model_copy(update={"beats": (*candidate.beats[:2], straddling, *candidate.beats[3:])})

    with pytest.raises(ValueError, match="ownership"):
        plan_repairs(_six_unit_source(), candidate, _SHARDS, (_failure("source_000005"),))


def test_spliced_repair_redirects_external_compression_to_replacement_beat() -> None:
    # These are visual beats; an external caption would be literal evidence
    # that must enter the replacement scope, not a compression-only link.
    template = _book_adaptation().beats[0].model_copy(update={"lettering": ()})
    original = _BookDraft(
        beats=(
            template.model_copy(
                update={
                    "id": "beat_0001",
                    "order": 1,
                    "source_unit_ids": ("source_000001",),
                }
            ),
            template.model_copy(
                update={
                    "id": "beat_0002",
                    "order": 2,
                    "source_unit_ids": ("source_000002",),
                }
            ),
        ),
        ledger=(
            AdaptationLedgerEntry(
                source_unit_id="source_000001",
                disposition="compressed_into",
                adapted_beat_ids=["beat_0002"],
                reason="The second beat carries the connection.",
                preserved_function="The connection remains explicit.",
            ),
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="depicted",
                adapted_beat_ids=["beat_0002"],
                preserved_function="The destination is depicted.",
            ),
        ),
    )
    repair = _BookDraft(
        beats=(
            template.model_copy(
                update={
                    "id": "beat_0001",
                    "order": 1,
                    "source_unit_ids": ("source_000002",),
                }
            ),
        ),
        ledger=(
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="depicted",
                adapted_beat_ids=["beat_0001"],
                preserved_function="The repaired destination is depicted.",
            ),
        ),
    )

    spliced = _splice_draft_repairs(
        original,
        [(repair, ("source_000002",))],
        {"source_000001": 1, "source_000002": 2},
    )

    assert spliced.ledger[0].adapted_beat_ids == ("beat_0002",)


def test_cross_scene_repair_cannot_drop_a_caption_outside_initial_scope() -> None:
    source_ids = ("source_000001", "source_000002")
    beat = _book_adaptation().beats[0]
    original = materialize_ledger(_BookDraft(beats=(beat,)), source_ids)
    scope = _closed_repair_scope(original, (source_ids[1],), source_ids)
    assert scope == source_ids
    # Reproduce the old failure: replacing the whole shared beat with a repair
    # that was only asked about the second source passage drops the first line.
    incomplete = beat.model_copy(update={
        "source_unit_ids": (source_ids[1],),
        "lettering": tuple(i for i in beat.lettering if source_ids[0] not in i.source_unit_ids),
    })
    repair = materialize_ledger(_BookDraft(beats=(incomplete,)), (source_ids[1],))
    with pytest.raises(ValueError, match="out-of-scope source evidence"):
        _splice_draft_repairs(original, [(repair, (source_ids[1],))], dict(zip(source_ids, (1, 2))))
    # A repair authored against the closed scope keeps both lines realized.
    spliced = _splice_draft_repairs(original, [(original, scope)], dict(zip(source_ids, (1, 2))))
    for entry in spliced.ledger:
        if entry.disposition in {"caption", "dialogue", "thought"}:
            assert any(entry.source_unit_id in i.source_unit_ids and i.kind == entry.disposition
                       for b in spliced.beats for i in b.lettering)
    assert [i.text for b in spliced.beats for i in b.lettering] == [i.text for i in beat.lettering]


def _three_visual_beats() -> _BookDraft:
    template = _book_adaptation().beats[0]
    beats = tuple(template.model_copy(update={
        "id": f"beat_{n:04d}", "order": n, "source_unit_ids": (f"source_{n:06d}",),
        "summary": f"Event {n}", "lettering": (),
    }) for n in range(1, 4))
    return materialize_ledger(_BookDraft(beats=beats), tuple(b.source_unit_ids[0] for b in beats))


@pytest.mark.parametrize("target_repaired", [False, True])
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_repair_batch_resolves_compression_across_shards(target_repaired, renamed, reverse):
    original = _three_visual_beats()
    origin, target = (2, 0) if reverse else (0, 2)
    first = _BookDraft(beats=(original.beats[origin],), ledger=(
        original.ledger[origin].model_copy(update={
            "disposition": "compressed_into", "adapted_beat_ids": (original.beats[target].id,),
            "reason": "This connection is disclosed with the other event.",
        }),
    ))
    repairs = [(first, original.beats[origin].source_unit_ids)]
    if target_repaired:
        beat = original.beats[target].model_copy(update={
            "id": "replacement" if renamed else original.beats[target].id,
            "summary": "Repaired destination",
        })
        repairs.append((_BookDraft(beats=(beat,), ledger=(original.ledger[target].model_copy(
            update={"adapted_beat_ids": (beat.id,)},
        ),)), beat.source_unit_ids))
    spliced = _splice_draft_repairs(original, repairs,
        {e.source_unit_id: n for n, e in enumerate(original.ledger)})
    assert spliced.ledger[origin].adapted_beat_ids == (spliced.beats[target].id,)
    assert spliced.beats[1] == original.beats[1]
    assert len(spliced.ledger) == 3
    # Repartitioning for the next repair/review must preserve global crosslinks.
    candidate = BookAdaptation.model_validate({**_book_adaptation().model_dump(),
        "content_sha256": "", "beats": spliced.beats, "ledger": spliced.ledger})
    partitions = partition_candidate(candidate, tuple(b.source_unit_ids for b in spliced.beats))
    merged, _ = merge_shard_drafts(partitions)
    assert merged.beats == spliced.beats
    assert merged.ledger == spliced.ledger


@pytest.mark.parametrize(("target", "disposition", "error"), [
    ("beat_9999", "compressed_into", "unknown external"),
    ("beat_0003", "depicted", "Only compression"),
])
def test_repair_batch_rejects_unsupported_external_destinations(target, disposition, error):
    original = _three_visual_beats()
    repair = _BookDraft(beats=(original.beats[0],), ledger=(original.ledger[0].model_copy(update={
        "disposition": disposition, "adapted_beat_ids": (target,), "reason": "Retimed claim",
    }),))
    with pytest.raises(ValueError, match=error):
        _splice_draft_repairs(original, [(repair, original.beats[0].source_unit_ids)],
            {e.source_unit_id: n for n, e in enumerate(original.ledger)})


def test_repair_batch_does_not_redirect_deleted_evidence_to_nearest_beat():
    original = _three_visual_beats()
    original = original.model_copy(update={"ledger": (
        original.ledger[0].model_copy(update={"disposition": "compressed_into",
            "adapted_beat_ids": ("beat_0002",), "reason": "Claim carried by the second event"}),
        *original.ledger[1:],
    )})
    repair = _BookDraft(beats=(original.beats[2],), ledger=(
        original.ledger[1].model_copy(update={"disposition": "intentionally_omitted",
            "adapted_beat_ids": (), "reason": "Event omitted"}), original.ledger[2],
    ))
    with pytest.raises(ValueError, match="without a supported destination"):
        _splice_draft_repairs(original, [(repair, ("source_000002", "source_000003"))],
            {e.source_unit_id: n for n, e in enumerate(original.ledger)})


def test_repair_batch_rejects_cyclic_compression_and_overlapping_scopes():
    original = _three_visual_beats()
    repairs = []
    for n in range(2):
        beat = original.beats[n].model_copy(update={"id": f"replacement_{n}"})
        repair = _BookDraft(beats=(beat,), ledger=(original.ledger[n].model_copy(update={
            "disposition": "compressed_into", "adapted_beat_ids": (original.beats[1 - n].id,),
            "reason": "Claim carried by the other event",
        }),))
        repairs.append((repair, beat.source_unit_ids))
    order = {e.source_unit_id: n for n, e in enumerate(original.ledger)}
    with pytest.raises(ValueError, match="cyclic destination"):
        _splice_draft_repairs(original, repairs, order)
    with pytest.raises(ValueError, match="scopes overlap"):
        _splice_draft_repairs(original, [repairs[0], repairs[0]], order)


def test_repair_scope_closes_transitively_over_shared_beats() -> None:
    template = _book_adaptation().beats[0].model_copy(update={"lettering": ()})
    draft = _BookDraft(beats=(
        template.model_copy(update={"id": "first", "source_unit_ids": ("a", "b")}),
        template.model_copy(update={"id": "second", "source_unit_ids": ("b", "c")}),
        template.model_copy(update={"id": "unrelated", "source_unit_ids": ("d",)}),
    ))
    assert _closed_repair_scope(draft, ("a",), ("a", "b", "c", "d")) == ("a", "b", "c")
    with pytest.raises(ValueError, match="unowned source"):
        _closed_repair_scope(draft, ("a",), ("a", "b"))


def test_repair_preserves_authored_flashback_order_instead_of_sorting_citations():
    # Captured raid repair: conference (151), raid (135), aftermath (126).
    # Earliest citations are summaries, not the desired order of dramatization.
    template = _book_adaptation().beats[0].model_copy(update={"lettering": ()})
    ids = ("source_000001", "source_000126", "source_000135", "source_000151", "source_000200")
    original = materialize_ledger(_BookDraft(beats=tuple(
        template.model_copy(update={"id": f"old_{n}", "order": n,
                                    "summary": f"old {n}", "source_unit_ids": (u,)})
        for n, u in enumerate(ids, 1)
    )), ids)
    scope = ids[1:4]
    repair = materialize_ledger(_BookDraft(beats=tuple(
        template.model_copy(update={"id": f"new_{n}", "order": n,
                                    "summary": label, "source_unit_ids": (u,)})
        for n, (u, label) in enumerate(zip(reversed(scope), ("conference", "raid", "aftermath")), 1)
    )), scope)
    spliced = _splice_draft_repairs(original, [(repair, scope)], dict(zip(ids, range(5))))
    assert [b.summary for b in spliced.beats] == ["old 1", "conference", "raid", "aftermath", "old 5"]
    assert {e.source_unit_id for e in spliced.ledger} == set(ids)
    assert [b.order for b in spliced.beats] == list(range(1, 6))


def test_repair_closes_over_intervening_authored_beats():
    template = _book_adaptation().beats[0].model_copy(update={"lettering": ()})
    draft = _BookDraft(beats=tuple(
        template.model_copy(update={"id": f"b{n}", "order": n, "source_unit_ids": (u,)})
        for n, u in enumerate(("a", "c", "b", "d"), 1)
    ))
    assert _closed_repair_scope(draft, ("a", "b"), ("a", "b", "c", "d")) == ("a", "b", "c")
    with pytest.raises(ValueError, match="out-of-scope"):
        _splice_draft_repairs(draft, [(draft, ("a", "b"))], dict(zip("abcd", range(4))))


def test_partition_for_repair_retains_the_reviewers_global_identifiers():
    a = _book_adaptation()
    template = a.beats[0]
    beats = tuple(template.model_copy(update={
        "id": f"beat_{n:04d}", "order": n, "source_unit_ids": (f"source_{n:06d}",),
        "lettering": (template.lettering[0].model_copy(update={
            "id": f"lettering_{n:04d}", "source_unit_ids": (f"source_{n:06d}",),
        }),),
    }) for n in range(1, 4))
    ledger = tuple(AdaptationLedgerEntry(source_unit_id=b.source_unit_ids[0], disposition="caption",
        adapted_beat_ids=(b.id,), preserved_function="Narrative continuity") for b in beats)
    candidate = a.model_copy(update={"beats": beats, "ledger": ledger})
    shards = (("source_000001",), ("source_000002", "source_000003"))
    drafts = partition_candidate(candidate, shards)
    assert drafts[1].beats[0].id == "beat_0002"
    assert drafts[1].beats[0].lettering[0].id == "lettering_0002"
    merged, _ = merge_shard_drafts(drafts)
    assert merged.beats == candidate.beats
    assert merged.ledger == candidate.ledger
    with pytest.raises(ValueError, match="ownership"):
        partition_candidate(candidate, (("source_000001",), ("source_000002",)))


def test_repair_preserves_exclusive_requirements_without_requiring_retained_ones():
    candidate = _book_adaptation()
    beat = candidate.beats[0]
    scoped = beat.model_copy(update={'id': 'scoped', 'source_unit_ids': ('source_000001',),
        'brief_requirement_ids': ('essential_event_001', 'essential_event_002')})
    retained = beat.model_copy(update={'id': 'retained', 'source_unit_ids': ('source_000002',),
        'brief_requirement_ids': ('essential_event_001',)})
    candidate = candidate.model_copy(update={'beats': (scoped, retained)})
    assert _repair_required_requirements(candidate, ('source_000001',)) == ('essential_event_002',)
