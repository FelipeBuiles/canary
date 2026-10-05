"""Provider-free editorial review, repair, freshness and admission regressions."""

from __future__ import annotations

from .plan_detail_support import detail_response, plan_response

import asyncio
from datetime import datetime, timezone
import json

import pytest

from novel_to_comic.narrative_review import (
    NarrativeFinding,
    NarrativePassage,
    _finding_identity,
    adaptation_context,
    narrative_signals,
    planning_context,
    require_draw_narrative_reviews,
    require_narrative_review,
    review_narrative,
    _review_prompts,
)
from novel_to_comic.models.page import ApprovedPageRange
from novel_to_comic.page_planning import (
    _BookPlanDraft,
    _canonical_pages,
    _normalize_book_plan_draft,
    produce_book_plan,
    PlanInvariantError,
)
from novel_to_comic.book_adaptation import (
    produce_book_adaptation,
    AdaptationInvariantError,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord
from .test_page_planning import _long_adaptation, _inventory
from .test_book_adaptation import (
    _source_document,
    _approved_brief,
    _story_bible,
    _book_adaptation,
    _blueprint_response,
    _lettering_response,
)


def runtime(tmp_path, stage):
    return StageRuntime(
        stage,
        PipelineState(
            project_name="review",
            novel_path="source.txt",
            created_at=datetime.now(timezone.utc),
        ),
        tmp_path,
    )


def test_same_cited_finding_has_one_identity_across_overlapping_windows():
    first = NarrativeFinding(
        code="repeated_event", repair_stage="adapt",
        artifact_ids=("beat_0017", "lettering_0056", "beat_0018", "lettering_0058"),
        evidence="The event is repeated.", repair="Stage it once.",
        consequence="unintelligible_sequence", reader_impact="Chronology appears to reset.",
        passages=(
            NarrativePassage(artifact_id="lettering_0056", quote="The door opens."),
            NarrativePassage(artifact_id="lettering_0058", quote=" The   door opens. "),
        ),
    )
    second = first.model_copy(update={
        "artifact_ids": ("beat_0018", "lettering_0058", "lettering_0056", "beat_0017"),
        "evidence": "A second reviewer described the same defect differently.",
    })

    assert _finding_identity(first) == _finding_identity(second)


def draft_for(adaptation, padding=0):
    beats = list(adaptation.beats) + [adaptation.beats[-1]] * padding
    return plan_response({
        "rhythm_summary": "A story, followed by an atmospheric ending.",
        "pages": [
            {
                "page_number": n,
                "emphasis": "initial",
                "density_intent": "standard",
                "rhythm_intent": "Advance the story."
                if n <= len(adaptation.beats)
                else "Atmospheric closing vigil.",
                "layout_intent": "A meaningful scene.",
                "content": [
                    {
                        "beat_ids": [b.id],
                        "camera": {"shot": "medium", "angle": "eye_level"},
                        "acting": [],
                        "visual_intent": b.summary,
                        "lettering_ids": [i.id for i in b.lettering]
                        if n <= len(adaptation.beats)
                        else [],
                    }
                ],
            }
            for n, b in enumerate(beats, 1)
        ],
    })


def canonical(adaptation, draft):
    return _canonical_pages(
        adaptation,
        _BookPlanDraft.model_validate(_normalize_book_plan_draft(draft, adaptation)),
        {},
        _inventory(),
    )


def verdict(request, *, accept=True, finding=None):
    context = json.JSONDecoder().raw_decode(request["user_content"].split("\n", 1)[1])[
        0
    ]
    # Existing repair/resume fixtures explicitly model substantive defects.
    # Supply the new evidence contract; policy tests below build unsubstantiated
    # responses directly rather than using this authoring fixture.
    if finding and finding["code"] in {"missing_context", "repeated_event", "unsupported_event"}:
        from novel_to_comic.narrative_review import _passage_texts
        texts = _passage_texts(context)
        finding = dict(finding)
        anchors = list(finding["artifact_ids"])
        passages = [{"artifact_id": a, "quote": next(t for t in texts[a] if t)}
                    for a in anchors if any(texts.get(a, []))]
        consequence = "unintelligible_sequence" if finding["code"] == "missing_context" else "contradiction"
        if consequence == "contradiction" and len(passages) < 2:
            primary = anchors[0]
            beat = next((b for b in context["beats"] if b["id"] == primary
                         or any(i["id"] == primary for i in b["lettering"])), None)
            candidates = beat.get("source_unit_ids", []) if beat else []
            if primary.startswith("page_"):
                p = next(p for p in context["pages"] if f"page_{p['page_number']:03d}" == primary)
                candidates = p.get("beat_ids", []) or [b for c in p.get("content", []) for b in c["beat_ids"]]
            extra = next((a for a in candidates if a not in anchors and any(texts.get(a, []))), None)
            if extra:
                anchors.append(extra)
                passages.append({"artifact_id": extra, "quote": next(t for t in texts[extra] if t)})
        finding = {**finding, "artifact_ids": anchors, "consequence": consequence,
                   "reader_impact": finding["evidence"], "passages": passages}
    return {
        "findings": [finding] if finding else [],
        "signal_assessments": [
            {
                "signal_id": s["id"],
                "acceptable": accept,
                "evidence": "The final event is already complete; these pages repeat an empty vigil."
                if not accept
                else "Each silent panel advances a distinct visible action with established actors and stakes.",
            }
            for s in context["signals"]
        ],
    }


def test_cthulhu_shape_flags_wordless_coda_and_last_beat_concentration():
    a = _long_adaptation(22)
    ctx = planning_context(a, canonical(a, draft_for(a, 12)))
    signals = narrative_signals(ctx)
    assert len(signals) == 2
    assert signals[0]["artifact_ids"] == [f"page_{n:03d}" for n in range(23, 35)]
    assert "13 of 34" in signals[1]["question"]


@pytest.mark.parametrize("sfx", [False, True])
def test_silence_signals_are_independent_of_model_story_function_labels(sfx):
    a = _long_adaptation(3)
    beats = [
        b.model_copy(
            update={
                "story_functions": (),
                "lettering": (
                    b.lettering[0].model_copy(update={"kind": "sfx", "text": "BANG"}),
                )
                if sfx
                else (),
            }
        )
        for b in a.beats
    ]
    context = {"phase": "adapt", "beats": [b.model_dump(mode="json") for b in beats]}
    assert narrative_signals(context)[0]["artifact_ids"] == [b.id for b in beats]


def test_legitimate_silence_is_reviewable_not_automatically_forbidden(tmp_path):
    a = _long_adaptation(2)
    context = planning_context(a, canonical(a, draft_for(a, 4)))

    async def generate(**request):
        return ApiResult(value=verdict(request))

    target = TargetArtifacts(tmp_path)
    assert (
        asyncio.run(
            review_narrative(
                context,
                generate=generate,
                ctx=runtime(tmp_path, "plan"),
                artifacts=target,
                model="test",
            )
        )
        == ()
    )
    require_narrative_review(target, "plan", context)


@pytest.mark.parametrize(
    "invalid", ["omitted_signal", "duplicate_signal", "unknown_anchor", "malformed"]
)
def test_incomplete_or_fabricated_review_fails_closed(tmp_path, invalid):
    a = _long_adaptation(2)
    context = planning_context(a, canonical(a, draft_for(a, 4)))

    async def generate(**request):
        value = verdict(request)
        if invalid == "omitted_signal":
            value["signal_assessments"] = []
        if invalid == "duplicate_signal":
            value["signal_assessments"].append(value["signal_assessments"][0])
        if invalid == "unknown_anchor":
            value["findings"] = [
                {
                    "code": "padding",
                    "repair_stage": "plan",
                    "artifact_ids": ["invented_page"],
                    "evidence": "Wrong.",
                    "repair": "Remove it.",
                }
            ]
        if invalid == "malformed":
            value = {"success": True}
        return ApiResult(value=value)

    target = TargetArtifacts(tmp_path)
    failures = asyncio.run(
        review_narrative(
            context,
            generate=generate,
            ctx=runtime(tmp_path, "plan"),
            artifacts=target,
            model="test",
        )
    )
    assert failures[0].code == "narrative_review_invalid"
    with pytest.raises(ValueError, match="failed or stale"):
        require_narrative_review(target, "plan", context)


@pytest.mark.parametrize("anchor", ["essential_event_001", "character_turn_001", "essential_event_999"])
def test_review_requirement_citations_are_exact_and_route_to_source(tmp_path, anchor):
    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    async def generate(**request):
        return ApiResult(value=verdict(request, finding={
            "code": "rushed_sequence", "repair_stage": "adapt", "artifact_ids": [anchor],
            "evidence": "An approved development is not clear in the words.",
            "repair": "Establish the development explicitly.",
        }))
    failures = asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
        artifacts=TargetArtifacts(tmp_path), model="test"))
    if anchor.endswith("999"):
        assert failures[0].code == "narrative_review_invalid"
        assert anchor in failures[0].evidence[0]
    else:
        assert not failures
        issues = TargetArtifacts(tmp_path).read_narrative_review("adapt").editorial_issues
        assert issues[0].code == "narrative_review_rushed_sequence"
        assert issues[0].artifact_ids == (anchor,)
        assert issues[0].source_unit_ids == ("source_000001", "source_000002")


def test_fixed_validator_reuses_previously_rejected_response(tmp_path, monkeypatch):
    import novel_to_comic.narrative_review as module
    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    target = TargetArtifacts(tmp_path)
    async def generate(**request):
        return ApiResult(value=verdict(request, finding={
            "code": "rushed_sequence", "repair_stage": "adapt",
            "artifact_ids": ["beat_0001", "essential_event_001"],
            "evidence": "The approved development needs room.", "repair": "Clarify the development.",
        }))
    validate = module._validate_verdict
    def old_validator(*args, **kwargs):
        raise ValueError("Narrative review cites unknown evidence IDs.")
    monkeypatch.setattr(module, "_validate_verdict", old_validator)
    failures = asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
        artifacts=target, model="test"))
    assert failures[0].code == "narrative_review_invalid"
    monkeypatch.setattr(module, "_validate_verdict", validate)
    async def no_new_request(**request):
        raise AssertionError("The saved response must be revalidated without regeneration")
    failures = asyncio.run(review_narrative(context, generate=no_new_request, ctx=runtime(tmp_path, "adapt"),
        artifacts=target, model="test"))
    assert not failures
    failures = TargetArtifacts(tmp_path).read_narrative_review("adapt").editorial_issues
    assert failures[0].code == "narrative_review_rushed_sequence"
    assert target.read_narrative_review("adapt").verdicts[0].findings[0].artifact_ids == (
        "beat_0001", "essential_event_001",
    )


@pytest.mark.parametrize("anchors", [
    ["beat_0002", "essential_event_001"],
    ["lettering_0002", "essential_event_001"],
    ["source_000002", "essential_event_001"],
])
def test_supplemental_requirement_does_not_expand_concrete_repair_scope(tmp_path, anchors):
    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    template = context["beats"][0]
    context["beats"] = [
        {**template, "id": f"beat_{n:04d}", "order": n, "source_unit_ids": [f"source_{n:06d}"],
         "brief_requirement_ids": ["essential_event_001"] if n == 1 else [],
         "lettering": [{**template["lettering"][n - 1], "id": f"lettering_{n:04d}",
                        "source_unit_ids": [f"source_{n:06d}"]}]}
        for n in (1, 2)
    ]
    context["ledger"] = [{**entry, "adapted_beat_ids": [f"beat_{n:04d}"]}
                         for n, entry in enumerate(context["ledger"], 1)]
    async def generate(**request):
        return ApiResult(value=verdict(request, finding={
            "code": "rushed_sequence", "repair_stage": "adapt", "artifact_ids": anchors,
            "evidence": "The later development needs clarification; the requirement explains its importance.",
            "repair": "Clarify the later beat.",
        }))
    failures = asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
        artifacts=TargetArtifacts(tmp_path), model="test"))
    assert not failures
    failures = TargetArtifacts(tmp_path).read_narrative_review("adapt").editorial_issues
    assert failures[0].code == "narrative_review_rushed_sequence"
    assert failures[0].artifact_ids == tuple(anchors)
    assert failures[0].source_unit_ids == ("source_000002",)

def test_invalid_review_retry_does_not_regenerate_valid_windows(tmp_path):
    a = _long_adaptation(30)
    context = planning_context(a, canonical(a, draft_for(a)))
    target = TargetArtifacts(tmp_path)
    first_calls = []
    async def first(**request):
        first_calls.append(request["user_content"])
        return ApiResult(value=verdict(request) if len(first_calls) == 1 else {"wrong": True})
    failures = asyncio.run(review_narrative(context, generate=first, ctx=runtime(tmp_path, "plan"),
        artifacts=target, model="test"))
    assert failures[-1].id == "plan_review_invalid_2"
    later_calls = []
    async def later(**request):
        later_calls.append(request["user_content"])
        # The recovery instruction follows the unchanged JSON context.
        original = {**request, "user_content": request["user_content"].split("\nRecheck")[0]}
        return ApiResult(value=verdict(original))
    assert not asyncio.run(review_narrative(context, generate=later, ctx=runtime(tmp_path, "plan"),
        artifacts=target, model="test"))
    assert len(later_calls) == 2  # retry window 2, then previously unreviewed window 3
    assert "\nRecheck" in later_calls[0]
    assert "\nRecheck" not in later_calls[1]
    assert first_calls[0] not in later_calls


def test_missing_invalid_response_still_has_a_bounded_two_request_correction(tmp_path):
    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    target = TargetArtifacts(tmp_path)
    calls = []
    async def invalid(**request):
        calls.append(request)
        return ApiResult(value={"wrong": True})
    for attempt in range(2):
        failures = asyncio.run(review_narrative(context, generate=invalid, ctx=runtime(tmp_path, "adapt"),
            artifacts=target, model="test"))
        assert failures[0].code == "narrative_review_invalid"
        assert len(calls) == (attempt + 1) * 2
        for path in (tmp_path / ".checkpoints/adapt/responses").glob("*.json"):
            path.unlink()


def test_review_cache_is_input_scoped_and_usage_is_recorded_once(tmp_path):
    a = _long_adaptation(2)
    context = planning_context(a, canonical(a, draft_for(a)))
    calls = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=verdict(request),
            usage=UsageRecord(
                provider="test", model="test", operation="text", cost_usd=0.01
            ),
        )

    target = TargetArtifacts(tmp_path)
    ctx = runtime(tmp_path, "plan")
    for _ in range(2):
        asyncio.run(
            review_narrative(
                context, generate=generate, ctx=ctx, artifacts=target, model="test"
            )
        )
    assert len(calls) == 1
    assert ctx.stage_state.cost_usd == 0.01
    changed = {
        **context,
        "pages": [dict(p, rhythm_intent="Changed") for p in context["pages"]],
    }
    with pytest.raises(ValueError, match="stale"):
        require_narrative_review(target, "plan", changed)
    asyncio.run(
        review_narrative(
            changed, generate=generate, ctx=ctx, artifacts=target, model="test"
        )
    )
    assert len(calls) == 2
    record = target.read_narrative_review("plan")
    target.write_narrative_review("plan", record.model_copy(update={"version": "old"}))
    with pytest.raises(ValueError, match="stale"):
        require_narrative_review(target, "plan", changed)


def test_plan_preserves_pacing_choices_without_editorial_retries(tmp_path):
    a = _long_adaptation(22)
    calls = []
    book_calls = 0

    async def generate(**request):
        nonlocal book_calls
        calls.append(request)
        if request["feature"] == "plan.book":
            book_calls += 1
            if book_calls == 2:
                assert "narrative_review_" in request["user_content"]
                assert "change page count" in request["user_content"]
            return ApiResult(value=draft_for(a, 12 if book_calls == 1 else 0))
        return ApiResult(value=verdict(request, accept=book_calls > 1))

    target = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            a,
            _inventory(),
            ApprovedPageRange(minimum=34, maximum=44),
            artifacts=target,
            ctx=runtime(tmp_path, "plan"),
            model="test",
            generate=generate,
        )
    )
    assert len(plan.pages) == 34
    assert plan.target_page_min == 34
    assert book_calls == 1
    assert target.read_validation("plan").editorial_issues
    assert not target.read_validation("plan").blocked
    require_narrative_review(
        target, "plan", planning_context(a, [target.read_page(n) for n in range(1, 35)])
    )


def test_persistent_padding_is_visible_without_blocking_publication(tmp_path):
    a = _long_adaptation(22)

    async def generate(**request):
        if request["feature"] == "plan.book":
            return ApiResult(value=draft_for(a, 12))
        return ApiResult(value=verdict(request, accept=False))

    target = TargetArtifacts(tmp_path)
    asyncio.run(
        produce_book_plan(
            a,
            _inventory(),
            ApprovedPageRange(minimum=34, maximum=44),
            artifacts=target,
            ctx=runtime(tmp_path, "plan"),
            model="test",
            generate=generate,
        )
    )
    assert target.plan_path.exists()
    assert not target.read_validation("plan").blocked
    assert target.read_validation("plan").editorial_issues


def test_map_review_padding_does_not_repeat_map_or_detail_generation(tmp_path):
    a = _long_adaptation(24)
    maps = 0
    details = 0

    async def generate(**request):
        nonlocal maps, details
        if request["feature"] == "plan.map":
            maps += 1
            raw = draft_for(a, 14 if maps == 1 else 0)
            return ApiResult(
                value={
                    "rhythm_summary": raw["rhythm_summary"],
                    "pages": [
                        {
                            "page_number": p["page_number"],
                            "beat_ids": p["content"][0]["beat_ids"],
                            "lettering_ids": p["content"][0]["lettering_ids"],
                            "emphasis": "initial",
                            "density_intent": "standard",
                            "rhythm_intent": p["rhythm_intent"],
                        }
                        for p in raw["pages"]
                    ],
                }
            )
        if request["feature"] == "plan.detail":
            details += 1
            assert maps == 1
            context = json.JSONDecoder().raw_decode(
                request["user_content"].split("\n", 1)[1]
            )[0]
            numbers = context["target_page_numbers"]
            raw = draft_for(a, 14)
            return ApiResult(
                value=detail_response({
                    **raw,
                    "pages": [p for p in raw["pages"] if p["page_number"] in numbers],
                })
            )
        return ApiResult(value=verdict(request, accept=maps > 1))

    target = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            a,
            _inventory(),
            ApprovedPageRange(minimum=34, maximum=44),
            artifacts=target,
            ctx=runtime(tmp_path, "plan"),
            model="test",
            generate=generate,
        )
    )
    assert len(plan.pages) == 38 and maps == 1 and details == 5


def test_adapt_editorial_failure_gets_one_repair_and_blocks_publication(tmp_path):
    a = _book_adaptation()
    calls = []

    async def generate(**request):
        calls.append(request["feature"])
        if request["feature"] == "adapt.narrative_treatment":
            return ApiResult(value=a.treatment.model_dump(mode="json"))
        if request["feature"] == "adapt.blueprint":
            return ApiResult(
                value=_blueprint_response(a.beats, include_legacy_ledger=True)
            )
        if request["feature"] == "adapt.lettering":
            return ApiResult(value=_lettering_response(a.beats))
        if request["feature"] == "adapt.narrative_review":
            return ApiResult(
                value=verdict(
                    request,
                    finding={
                        "code": "repeated_event",
                        "repair_stage": "adapt",
                        "artifact_ids": [a.beats[0].id],
                        "evidence": "The manuscript is acquired twice without a flashback cue.",
                        "repair": "Stage the acquisition once; preserve the aftermath.",
                    },
                )
            )
        assert "narrative_review_repeated_event" in request["user_content"]
        return ApiResult(
            value={
                "beats": [b.model_dump(mode="json") for b in a.beats],
                "ledger": [entry.model_dump(mode="json") for entry in a.ledger],
            }
        )

    target = TargetArtifacts(tmp_path)
    with pytest.raises(AdaptationInvariantError):
        asyncio.run(
            produce_book_adaptation(
                _source_document(),
                _story_bible(),
                _approved_brief(),
                artifacts=target,
                ctx=runtime(tmp_path, "adapt"),
                model="test",
                generate=generate,
            )
        )
    assert not target.adaptation_path.exists()
    assert target.failed_adaptation_candidate_path.exists()
    assert target.read_validation("adapt").blocked
    assert "adapt.book" in calls


def test_review_windows_include_omitted_source_and_cross_boundary_context():
    a = _book_adaptation()
    context = adaptation_context(_source_document(), _approved_brief(), a)
    context["units"] = [
        {"id": f"omitted_{n}", "text": "x" * 13000} for n in range(3)
    ] + context["units"]
    prompts = [json.loads(p.split("\n", 1)[1]) for p in _review_prompts(context)]
    assert {u["id"] for p in prompts for u in p["units"]} == {
        u["id"] for u in context["units"]
    }
    assert all(p["global_story"] for p in prompts)


def test_draw_admission_requires_both_current_reviews(tmp_path):
    target = TargetArtifacts(tmp_path)
    a = _book_adaptation()
    source = _source_document()
    brief = _approved_brief()
    target.write_source(source)
    target.write_brief(brief)
    target.write_adaptation(a)
    with pytest.raises(ValueError, match="Resume adaptation"):
        require_draw_narrative_reviews(target)

    async def generate(**request):
        return ApiResult(value=verdict(request))

    asyncio.run(
        review_narrative(
            adaptation_context(source, brief, a),
            generate=generate,
            ctx=runtime(tmp_path, "adapt"),
            artifacts=target,
            model="test",
        )
    )
    # A completed adaptation review alone cannot authorize drawing.
    from novel_to_comic.models.page import BookPlan, PlannedPageRevision

    pages = canonical(a, draft_for(a))
    for p in pages:
        target.write_page(p)
    target.write_plan(
        BookPlan(
            revision=1,
            adaptation_revision=a.revision,
            adaptation_sha256=a.content_sha256,
            target_page_min=1,
            target_page_max=2,
            pages=[
                PlannedPageRevision(
                    page_number=p.page_number,
                    revision=p.revision,
                    content_sha256=p.content_sha256,
                )
                for p in pages
            ],
        )
    )
    with pytest.raises(ValueError, match="Rerun Plan"):
        require_draw_narrative_reviews(target)
    asyncio.run(
        review_narrative(
            planning_context(a, pages),
            generate=generate,
            ctx=runtime(tmp_path, "plan"),
            artifacts=target,
            model="test",
        )
    )
    require_draw_narrative_reviews(target)
    changed = type(pages[0]).model_validate(
        {
            **pages[0].model_dump(),
            "content_sha256": "",
            "layout_intent": "Different story action.",
        }
    )
    target.write_page(changed)
    with pytest.raises(ValueError, match="Rerun Plan"):
        require_draw_narrative_reviews(target)


@pytest.mark.parametrize("entry", ["batch", "individual", "correction", "stage"])
def test_draw_entry_points_stop_before_preparation_without_reviews(
    tmp_path, monkeypatch, entry
):
    from unittest.mock import Mock
    from fastapi import HTTPException
    from novel_to_comic.config import Config
    from novel_to_comic.server.routers import pages
    from novel_to_comic.stages import s7_page_draw
    from novel_to_comic.target_artifacts import ArtifactMissing

    prepare = Mock(
        side_effect=AssertionError("No renderer preparation before narrative admission")
    )
    monkeypatch.setattr(pages, "complete_page_adapter", prepare)
    project = (tmp_path, Config(), runtime(tmp_path, "draw").state)
    with pytest.raises((ArtifactMissing, ValueError, HTTPException)):
        if entry == "batch":
            pages.prepare_undrawn_pages(project_dir=tmp_path, config=Config())
        elif entry == "individual":
            pages._prepare_initial_generation(project, 1, "canonical")
        elif entry == "correction":
            pages._prepare_explicit_correction(
                target=TargetArtifacts(tmp_path),
                page_number=1,
                body=None,
                config=Config(),
            )
        else:
            asyncio.run(s7_page_draw.run(Config(), tmp_path, runtime(tmp_path, "draw")))
    prepare.assert_not_called()


def test_plan_time_script_finding_is_advisory_and_does_not_replan(tmp_path):
    # Plan's reviewer sees the script, never the source, so it cannot verify
    # copy or events; Adapt's source-backed review already governs them.
    a = _long_adaptation(2)
    book_calls = 0

    async def generate(**request):
        nonlocal book_calls
        if request["feature"] == "plan.book":
            book_calls += 1
            return ApiResult(value=draft_for(a))
        return ApiResult(
            value=verdict(
                request,
                finding={
                    "code": "missing_context",
                    "repair_stage": "adapt",
                    "artifact_ids": [a.beats[0].id],
                    "evidence": "The deduction is absent from canonical lettering.",
                    "repair": "Add the deduction in Adapt before reallocating pages.",
                },
            )
        )

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            a,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=4),
            artifacts=artifacts,
            ctx=runtime(tmp_path, "plan"),
            model="test",
            generate=generate,
        )
    )
    assert plan.pages
    assert book_calls == 1
    review = artifacts.read_narrative_review("plan")
    assert not review.failures
    assert [i.code for i in review.editorial_issues] == ["narrative_review_missing_context"]
    assert "Adapt's source-backed review" in review.editorial_issues[0].message


def test_author_instruction_is_reviewed_and_part_of_cache_identity(tmp_path):
    adaptation = _long_adaptation(2)
    context = planning_context(adaptation, canonical(adaptation, draft_for(adaptation)))
    calls = []

    async def generate(**request):
        supplied = json.JSONDecoder().raw_decode(
            request["user_content"].split("\n", 1)[1]
        )[0]
        calls.append(supplied["approved_story_instruction"])
        return ApiResult(value=verdict(request))

    target = TargetArtifacts(tmp_path)
    for instruction in ["End with a deliberate silent image.", "End with narration."]:
        asyncio.run(
            review_narrative(
                context,
                generate=generate,
                ctx=runtime(tmp_path, "plan"),
                artifacts=target,
                model="test",
                instruction=instruction,
            )
        )
    assert len(calls) == 2
    assert target.read_narrative_review("plan").instruction == calls[-1]


@pytest.mark.parametrize("resolved", [True, False])
def test_plan_staging_review_repairs_only_its_detail_batch(tmp_path, resolved):
    adaptation = _long_adaptation(24)
    maps, detail_starts = 0, []

    async def generate(**request):
        nonlocal maps
        raw = draft_for(adaptation)
        if request["feature"] == "plan.map":
            maps += 1
            return ApiResult(value={"rhythm_summary": raw["rhythm_summary"], "pages": [
                {"page_number": p["page_number"], "beat_ids": p["content"][0]["beat_ids"],
                 "lettering_ids": p["content"][0]["lettering_ids"], "emphasis": p["emphasis"],
                 "density_intent": p["density_intent"], "rhythm_intent": p["rhythm_intent"]}
                for p in raw["pages"]
            ]})
        supplied = json.JSONDecoder().raw_decode(request["user_content"].split("\n", 1)[1])[0]
        if request["feature"] == "plan.detail":
            numbers = supplied["target_page_numbers"]
            detail_starts.append(numbers[0])
            repair = "PREVIOUS DETAIL:" in request["user_content"]
            if repair:
                assert numbers == list(range(17, 25))
                assert "seal the idol with the papers" in request["user_content"]
            for page in raw["pages"]:
                page["content"].append({**page["content"][0], "lettering_ids": [],
                                        "camera": {"shot": "medium", "angle": "eye_level"},
                                        "acting": [],
                                        "visual_intent": "A distinct silent reaction to the event."})
            raw["pages"][-1]["content"][0]["visual_intent"] = (
                "seal only the papers; the idol is absent" if repair and resolved else "seal the idol with the papers"
            )
            return ApiResult(value=detail_response({**raw, "pages": [p for p in raw["pages"] if p["page_number"] in numbers]}))
        finding = None
        if supplied["phase"] == "plan" and any(
            c["visual_intent"] == "seal the idol with the papers"
            for p in supplied["pages"] for c in p["content"]
        ):
            finding = {"code": "unsupported_event", "repair_stage": "plan", "artifact_ids": ["page_024"],
                       "evidence": "The narrator never acquired the idol.", "repair": "Remove the idol from the sealed contents. Keep the words."}
        return ApiResult(value=verdict(request, finding=finding))

    target = TargetArtifacts(tmp_path)
    def run():
        return asyncio.run(produce_book_plan(adaptation, _inventory(), ApprovedPageRange(minimum=24, maximum=24),
            artifacts=target, ctx=runtime(tmp_path, "plan"), model="test", generate=generate))
    if resolved:
        plan = run()
        assert len(plan.pages) == 24
        assert target.read_page(24).content[0].visual_intent == "seal only the papers; the idol is absent"
        assert not target.plan_review_draft_path.exists()
    else:
        with pytest.raises(PlanInvariantError):
            run()
        assert not target.plan_path.exists()
        assert target.read_plan_review_draft().pages[-1].content[0].visual_intent == "seal the idol with the papers"
        assert target.read_validation("plan").blocked
    assert maps == 1
    assert sorted(detail_starts) == [1, 9, 17, 17]
    assert any("narrative_review_unsupported_event" in a.invariant_codes for a in target.read_validation("plan").attempt_history)


def test_narrative_finding_after_structural_repair_still_gets_its_own_repair(tmp_path):
    # Review runs only on a structurally valid draft. When the first draft needs
    # a structural repair, the first narrative finding arrives after it and must
    # not block without the one narrative repair Plan is owed.
    adaptation = _long_adaptation(24)
    repairs = []

    async def generate(**request):
        raw = draft_for(adaptation)
        if request["feature"] == "plan.map":
            return ApiResult(value={"rhythm_summary": raw["rhythm_summary"], "pages": [
                {"page_number": p["page_number"], "beat_ids": p["content"][0]["beat_ids"],
                 "lettering_ids": p["content"][0]["lettering_ids"], "emphasis": p["emphasis"],
                 "density_intent": p["density_intent"], "rhythm_intent": p["rhythm_intent"]}
                for p in raw["pages"]
            ]})
        supplied = json.JSONDecoder().raw_decode(request["user_content"].split("\n", 1)[1])[0]
        if request["feature"] == "plan.detail":
            numbers = supplied["target_page_numbers"]
            if "PREVIOUS DETAIL:" in request["user_content"]:
                repairs.append(request["user_content"])
            for page in raw["pages"]:
                page["content"].append({**page["content"][0], "lettering_ids": [],
                                        "visual_intent": "A distinct silent reaction to the event."})
            last = raw["pages"][-1]["content"][0]
            last["visual_intent"] = ("seal only the papers; the idol is absent" if len(repairs) == 2
                                     else "seal the idol with the papers")
            if 17 in numbers and not repairs:
                last["camera"] = None
            return ApiResult(value=detail_response({**raw, "pages": [p for p in raw["pages"] if p["page_number"] in numbers]}))
        finding = None
        if supplied["phase"] == "plan" and any(
            c["visual_intent"] == "seal the idol with the papers"
            for p in supplied["pages"] for c in p["content"]
        ):
            finding = {"code": "unsupported_event", "repair_stage": "plan", "artifact_ids": ["page_024"],
                       "evidence": "The narrator never acquired the idol.", "repair": "Remove the idol from the sealed contents. Keep the words."}
        return ApiResult(value=verdict(request, finding=finding))

    target = TargetArtifacts(tmp_path)
    plan = asyncio.run(produce_book_plan(adaptation, _inventory(), ApprovedPageRange(minimum=24, maximum=24),
        artifacts=target, ctx=runtime(tmp_path, "plan"), model="test", generate=generate))

    assert len(repairs) == 2
    assert "missing_panel_camera" in repairs[0]
    assert "seal the idol with the papers" in repairs[1]
    assert target.read_page(24).content[0].visual_intent == "seal only the papers; the idol is absent"
    history = target.read_validation("plan").attempt_history
    assert [a.invariant_codes for a in history[-3:]] == [
        ("missing_panel_camera",), ("narrative_review_unsupported_event",), (),
    ]
    assert len(plan.pages) == 24


def test_review_corrects_window_relative_page_citations_before_story_repair(tmp_path):
    adaptation = _long_adaptation(44)
    context = planning_context(adaptation, canonical(adaptation, draft_for(adaptation)), phase="plan_map")
    final_window_calls = 0
    async def generate(**request):
        nonlocal final_window_calls
        supplied = json.JSONDecoder().raw_decode(request["user_content"].split("\n", 1)[1])[0]
        if supplied["pages"][0]["page_number"] != 37:
            return ApiResult(value=verdict(request))
        final_window_calls += 1
        allowed = request["json_schema"]["$defs"]["NarrativeFinding"]["properties"]["artifact_ids"]["items"]["enum"]
        assert "page_003" not in allowed and "page_038" in allowed
        if final_window_calls == 2:
            assert "unknown evidence IDs: page_003, page_004" in request["user_content"]
        return ApiResult(value=verdict(request, finding={
            "code": "rushed_sequence", "repair_stage": "plan",
            "artifact_ids": ["page_003", "page_004"] if final_window_calls == 1 else ["page_038", "page_039"],
            "evidence": "Pages 38–39 disclose the emergence before the reveal spread.",
            "repair": "Keep the revealing words on page 39.",
        }))
    failures = asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "plan"),
        artifacts=TargetArtifacts(tmp_path), model="test"))
    assert final_window_calls == 2
    assert not failures
    failures = TargetArtifacts(tmp_path).read_narrative_review("plan_map").editorial_issues
    assert failures[0].artifact_ids == ("page_038", "page_039")
    assert set(failures[0].source_unit_ids) == set(adaptation.beats[37].source_unit_ids + adaptation.beats[38].source_unit_ids)


def test_final_two_pass_review_keeps_padding_advisory(tmp_path):
    adaptation = _long_adaptation(24)
    maps = 0

    async def generate(**request):
        nonlocal maps
        if request["feature"] == "plan.map":
            maps += 1
            raw = draft_for(adaptation)
            mapped = [
                {
                    "page_number": p["page_number"],
                    "beat_ids": p["content"][0]["beat_ids"],
                    "lettering_ids": p["content"][0]["lettering_ids"],
                    "emphasis": "initial",
                    "density_intent": "standard",
                    "rhythm_intent": p["rhythm_intent"],
                }
                for p in raw["pages"]
            ]
            if maps == 2:
                assert (
                    "Repair the global narrative allocation" in request["user_content"]
                )
                mapped[0]["beat_ids"] += mapped[1]["beat_ids"]
                mapped[0]["lettering_ids"] += mapped[1]["lettering_ids"]
                del mapped[1]
            return ApiResult(
                value={"rhythm_summary": "Varied story allocation.", "pages": mapped}
            )
        supplied = json.JSONDecoder().raw_decode(
            request["user_content"].split("\n", 1)[1]
        )[0]
        if request["feature"] == "plan.detail":
            raw = draft_for(adaptation)
            if maps == 2:
                raw["pages"][0]["content"] += raw["pages"][1]["content"]
                del raw["pages"][1]
                for n, page in enumerate(raw["pages"], 1):
                    page["page_number"] = n
            return ApiResult(
                value=detail_response({
                    **raw,
                    "pages": [
                        p
                        for p in raw["pages"]
                        if p["page_number"] in supplied["target_page_numbers"]
                    ],
                })
            )
        finding = None
        if supplied["phase"] == "plan" and maps == 1:
            finding = {
                "code": "padding",
                "repair_stage": "plan",
                "artifact_ids": [adaptation.beats[0].id],
                "evidence": "The opening repeats a moment over two pages.",
                "repair": "Combine the opening pair while keeping their exact words.",
            }
        # The critic's previous feedback is not promoted to author authority.
        assert supplied["approved_story_instruction"] == ""
        return ApiResult(value=verdict(request, finding=finding))

    target = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=34, maximum=44),
            artifacts=target,
            ctx=runtime(tmp_path, "plan"),
            model="test",
            generate=generate,
        )
    )
    assert maps == 1 and len(plan.pages) == 24
    assert not target.read_validation("plan").blocked
    assert any(i.code == "narrative_review_padding" for i in plan.editorial_issues)


def test_review_ledger_grouping_is_lossless():
    from novel_to_comic.narrative_review import _group_ledger
    entries = [e.model_dump(mode="json") for e in _book_adaptation().ledger]
    entries += [dict(entries[0], source_unit_id="extra_source")]
    grouped = _group_ledger(entries)
    expanded = [dict({k: v for k, v in g.items() if k != "source_unit_ids"}, source_unit_id=u)
                for g in grouped for u in g["source_unit_ids"]]
    assert sorted(expanded, key=lambda e: e["source_unit_id"]) == sorted(entries, key=lambda e: e["source_unit_id"])
    assert len(grouped) < len(entries)


def test_neighboring_lettering_has_its_source_evidence_in_each_review_window():
    from novel_to_comic.narrative_review import _review_contexts
    a = _long_adaptation(8)
    beats = [b.model_dump(mode="json") for b in a.beats]
    units = [{"id": u, "text": "source evidence " * 900}
             for b in beats for u in b["source_unit_ids"]]
    context = {"phase": "adapt", "beats": beats, "units": units,
               "ledger": [e.model_dump(mode="json") for e in a.ledger]}
    windows = list(_review_contexts(context))
    assert len(windows) > 1
    assert [u for w in windows for u in w["units"]] == units
    for w in windows:
        supplied = {u["id"] for u in w["units"] + w["supporting_units"]}
        assert {u for b in w["beats"] for u in b["source_unit_ids"]} <= supplied
        assert {u for b in w["beats"] for i in b["lettering"] for u in i["source_unit_ids"]} <= supplied


def test_lettering_findings_are_valid_and_map_to_exact_source(tmp_path):
    a = _book_adaptation()
    item = a.beats[0].lettering[0]
    context = adaptation_context(_source_document(), _approved_brief(), a)

    async def generate(**request):
        return ApiResult(value=verdict(request, finding={
            "code": "unsupported_event", "repair_stage": "adapt", "artifact_ids": [item.id],
            "evidence": "The named caption attributes knowledge before it is acquired.",
            "repair": "Keep only the knowledge available in the cited source.",
        }))

    failures = asyncio.run(review_narrative(context, generate=generate,
        ctx=runtime(tmp_path, "adapt"), artifacts=TargetArtifacts(tmp_path), model="test"))
    assert failures[0].code == "narrative_review_unsupported_event"
    assert failures[0].source_unit_ids == item.source_unit_ids


def test_global_signals_are_assessed_once_with_all_evidence(tmp_path):
    from novel_to_comic.narrative_review import _review_contexts
    a = _long_adaptation(2)
    context = planning_context(a, canonical(a, draft_for(a, 24)))
    windows = list(_review_contexts(context))
    assigned = [s["id"] for w in windows for s in w["signals"]]
    assert sorted(assigned) == sorted(s["id"] for s in narrative_signals(context))
    for w in windows:
        page_ids = {f"page_{p['page_number']:03d}" for p in w["pages"]}
        beat_ids = {b["id"] for b in w["beats"]}
        for signal in w["signals"]:
            assert set(signal["artifact_ids"]) <= page_ids | beat_ids
            if signal["id"].startswith("concentration"):
                assert len(w["pages"]) == 26

    async def generate(**request):
        return ApiResult(value=verdict(request))

    target = TargetArtifacts(tmp_path)
    assert not asyncio.run(review_narrative(context, generate=generate,
        ctx=runtime(tmp_path, "plan"), artifacts=target, model="test"))
    require_narrative_review(target, "plan", context)


def test_review_cache_tracks_distant_reader_copy_but_not_content_hash_alone():
    a = _long_adaptation(30)
    context = planning_context(a, canonical(a, draft_for(a)))
    changed = json.loads(json.dumps(context))
    changed["adaptation_sha256"] = "a different canonical hash"
    before = list(_review_prompts(context))
    assert before == list(_review_prompts(changed))
    changed["beats"][-1]["lettering"][0]["text"] += " Changed final wording."
    after = list(_review_prompts(changed))
    assert all(old != new for old, new in zip(before, after, strict=True))


@pytest.mark.parametrize("phase", ["adapt", "plan", "plan_map"])
def test_review_retains_chronology_outside_neighbor_radius_without_duplicate_copy(phase):
    from novel_to_comic.narrative_review import _review_contexts, _review_request

    a = _long_adaptation(30)
    context = planning_context(a, canonical(a, draft_for(a)))
    context["phase"] = phase
    beats = context["beats"]
    established = beats[9]["lettering"][0]
    established["text"] = "Once before, in 1908—seventeen years earlier—he had seen the idol."
    beats[10]["lettering"][0]["text"] = "The earlier experience had come at the St. Louis meeting."
    if phase == "adapt":
        context.pop("pages")
        context["units"] = [
            {"id": u, "text": "source evidence " * 900}
            for b in beats for u in b["source_unit_ids"]
        ]
        context["ledger"] = [e.model_dump(mode="json") for e in a.ledger]
    elif phase == "plan_map":
        context["pages"] = [
            {"page_number": n, "rhythm_intent": "Advance the story.",
             "beat_ids": [b["id"]], "lettering_ids": [i["id"] for i in b["lettering"]]}
            for n, b in enumerate(beats, 1)
        ]
    windows = list(_review_contexts(context))
    assert len(windows) > 1
    assert any(
        beats[9]["id"] in {b["id"] for b in w["reader_context"]}
        and beats[10]["id"] in {b["id"] for b in w["beats"]}
        for w in windows
    )
    for window in windows:
        detailed = {b["id"] for b in window["beats"]}
        outside = {b["id"] for b in window["reader_context"]}
        assert detailed.isdisjoint(outside)
        assert detailed | outside == {b["id"] for b in beats}
        copy = {b["id"]: b["lettering"] for b in window["beats"] + window["reader_context"]}
        assert [i["text"] for b in beats for i in copy[b["id"]]] == [
            i["text"] for b in beats for i in b["lettering"]
        ]
        request = _review_request(window)
        assert request["user_content"].count(established["text"]) == 1
        assert established["id"] in request["json_schema"]["$defs"]["NarrativeFinding"]["properties"]["artifact_ids"]["items"]["enum"]


def test_malformed_review_does_not_trigger_a_story_rewrite_and_candidate_survives(tmp_path):
    a = _book_adaptation()
    calls = []

    async def generate(**request):
        calls.append(request["feature"])
        return ApiResult(value={
            "adapt.narrative_treatment": a.treatment.model_dump(mode="json"),
            "adapt.blueprint": _blueprint_response(a.beats),
            "adapt.lettering": _lettering_response(a.beats),
            "adapt.narrative_review": {"wrong_contract": True},
        }[request["feature"]])

    target = TargetArtifacts(tmp_path)
    with pytest.raises(AdaptationInvariantError):
        asyncio.run(produce_book_adaptation(_source_document(), _story_bible(), _approved_brief(),
            artifacts=target, ctx=runtime(tmp_path, "adapt"), model="test", generate=generate))
    assert calls == ["adapt.narrative_treatment", "adapt.blueprint", "adapt.lettering",
                     "adapt.narrative_review", "adapt.narrative_review"]
    assert target.read_failed_adaptation_candidate().beats
    assert target.read_validation("adapt").blocked
    assert not target.adaptation_path.exists()


def test_review_transport_stop_preserves_candidate_without_publishing(tmp_path):
    a = _book_adaptation()
    async def generate(**request):
        if request["feature"] == "adapt.narrative_review":
            raise TimeoutError("stream outcome unknown")
        return ApiResult(value={
            "adapt.narrative_treatment": a.treatment.model_dump(mode="json"),
            "adapt.blueprint": _blueprint_response(a.beats),
            "adapt.lettering": _lettering_response(a.beats),
        }[request["feature"]])
    target = TargetArtifacts(tmp_path)
    with pytest.raises(TimeoutError):
        asyncio.run(produce_book_adaptation(_source_document(), _story_bible(), _approved_brief(),
            artifacts=target, ctx=runtime(tmp_path, "adapt"), model="test", generate=generate))
    assert target.read_failed_adaptation_candidate().beats
    assert not target.adaptation_path.exists()


def test_resume_repairs_latest_reviewed_candidate_instead_of_initial_draft(tmp_path):
    from novel_to_comic.book_adaptation import _reviewed_candidate_for_resume
    a = _book_adaptation()
    original = a.beats[0].lettering[0].text
    improved = "I saw the door open. I then fled into the rain, shaken by what I had seen."
    repaired = a.beats[0].model_copy(update={"lettering": (
        a.beats[0].lettering[0].model_copy(update={"text": improved}),
        *a.beats[0].lettering[1:],
    )})
    calls = []

    async def generate(**request):
        calls.append(request["feature"])
        if request["feature"] == "adapt.narrative_review":
            return ApiResult(value=verdict(request, finding={
                "code": "missing_context", "repair_stage": "adapt",
                "artifact_ids": [a.beats[0].id],
                "evidence": "The sequence still needs an explicit temporal distinction.",
                "repair": "Clarify when the narrator learned the fact.",
            }))
        return ApiResult(value={
            "adapt.narrative_treatment": a.treatment.model_dump(mode="json"),
            "adapt.blueprint": _blueprint_response(a.beats),
            "adapt.lettering": _lettering_response(a.beats),
            "adapt.book": {"beats": [repaired.model_dump(mode="json")],
                           "ledger": [e.model_dump(mode="json") for e in a.ledger]},
        }[request["feature"]])

    target = TargetArtifacts(tmp_path)
    source, bible, brief = _source_document(), _story_bible(), _approved_brief()
    with pytest.raises(AdaptationInvariantError):
        asyncio.run(produce_book_adaptation(source, bible, brief, artifacts=target,
            ctx=runtime(tmp_path, "adapt"), model="test", generate=generate))
    saved = target.read_failed_adaptation_candidate()
    assert saved.beats[0].lettering[0].text == improved != original
    assert _reviewed_candidate_for_resume(source, bible, brief, artifacts=target, model="test") == saved
    assert _reviewed_candidate_for_resume(source, bible, brief, artifacts=target, model="other") == saved
    assert _reviewed_candidate_for_resume(source, bible, brief, artifacts=target, model="test",
                                          story_instruction="New approved intent") is None
    assert _reviewed_candidate_for_resume(source, bible.model_copy(update={"title": "Changed authority"}),
                                          brief, artifacts=target, model="test") is None
    changed_source = source.model_copy(update={"source_sha256": "f" * 64})
    assert _reviewed_candidate_for_resume(changed_source, bible, brief, artifacts=target, model="test") is None

    resumed_calls = []
    async def resume(**request):
        resumed_calls.append(request["feature"])
        assert request["feature"] == "adapt.book"
        assert improved in request["user_content"]
        raise RuntimeError("Reached repair of the latest candidate")

    with pytest.raises(RuntimeError, match="latest candidate"):
        asyncio.run(produce_book_adaptation(source, bible, brief, artifacts=target,
            ctx=runtime(tmp_path, "adapt"), model="test", generate=resume))
    assert resumed_calls == ["adapt.book"]
    assert target.read_failed_adaptation_candidate() == saved
    assert not target.adaptation_path.exists()


@pytest.mark.parametrize("next_model", ["test", "other"])
@pytest.mark.parametrize("has_work_checkpoint", [False, True])
def test_resume_after_splice_crash_reuses_complete_unchecked_repair(
    tmp_path, monkeypatch, next_model, has_work_checkpoint,
):
    import novel_to_comic.book_adaptation as module
    a = _book_adaptation()
    improved = "I saw the door open. I then fled into the rain, shaken by what I had seen."
    repaired = a.beats[0].model_copy(update={"lettering": (
        a.beats[0].lettering[0].model_copy(update={"text": improved}), *a.beats[0].lettering[1:],
    )})
    calls = []
    async def generate(**request):
        calls.append(request["feature"])
        if request["feature"] == "adapt.narrative_review":
            return ApiResult(value=verdict(request, finding={
                "code": "missing_context", "repair_stage": "adapt", "artifact_ids": [a.beats[0].id],
                "evidence": "The reaction needs context.", "repair": "Clarify the reaction.",
            }))
        return ApiResult(value={
            "adapt.narrative_treatment": a.treatment.model_dump(mode="json"),
            "adapt.blueprint": _blueprint_response(a.beats),
            "adapt.lettering": _lettering_response(a.beats),
            "adapt.book": {"beats": [repaired.model_dump(mode="json")]},
        }[request["feature"]])

    splice = module._splice_draft_repairs
    def crash(*args):
        raise KeyError("beat_0048")
    monkeypatch.setattr(module, "_splice_draft_repairs", crash)
    target = TargetArtifacts(tmp_path)
    def run(generator, model="test"):
        return asyncio.run(produce_book_adaptation(_source_document(), _story_bible(), _approved_brief(),
            artifacts=target, ctx=runtime(tmp_path, "adapt"), model=model, generate=generator))
    with pytest.raises(KeyError, match="beat_0048"):
        run(generate)
    assert calls.count("adapt.book") == 1
    assert list(tmp_path.rglob("round_01_shard_001.json"))
    assert not list(tmp_path.rglob("checked_*.json"))
    if not has_work_checkpoint:
        for path in (tmp_path / ".checkpoints/adapt/candidate").glob("*.json"):
            path.unlink()
    monkeypatch.setattr(module, "_splice_draft_repairs", splice)
    resumed = []
    async def review_only(**request):
        resumed.append(request["feature"])
        assert request["feature"] == "adapt.narrative_review"
        assert improved in request["user_content"]
        return ApiResult(value=verdict(request))
    result = run(review_only, next_model)
    assert resumed == ["adapt.narrative_review"]
    assert result.beats[0].lettering[0].text == improved
    assert len(list(tmp_path.rglob("checked_*.json"))) == 1


def test_budget_stop_before_review_preserves_repair_across_model_switch(tmp_path, monkeypatch):
    from novel_to_comic.generation_budget import GenerationWorkLimitError
    from novel_to_comic.book_adaptation import _resume_adaptation_work
    a = _book_adaptation()
    improved = "I saw the door open. I then fled into the rain, shaken by what I had seen."
    repaired = a.beats[0].model_copy(update={"lettering": (
        a.beats[0].lettering[0].model_copy(update={"text": improved}), *a.beats[0].lettering[1:],
    )})
    calls = []
    async def generate(**request):
        calls.append(request["feature"])
        if request["feature"] == "adapt.narrative_review":
            return ApiResult(value=verdict(request, finding={
                "code": "missing_context", "repair_stage": "adapt", "artifact_ids": [a.beats[0].id],
                "evidence": "The reaction needs context.", "repair": "Clarify the reaction.",
            }))
        return ApiResult(value={
            "adapt.narrative_treatment": a.treatment.model_dump(mode="json"),
            "adapt.blueprint": _blueprint_response(a.beats),
            "adapt.lettering": _lettering_response(a.beats),
            "adapt.book": {"beats": [repaired.model_dump(mode="json")]},
        }[request["feature"]])

    source, bible, brief = _source_document(), _story_bible(), _approved_brief()
    target = TargetArtifacts(tmp_path)
    def run(model, generate, limit=None):
        return asyncio.run(produce_book_adaptation(source, bible, brief, artifacts=target,
            ctx=runtime(tmp_path, "adapt"), model=model, generate=generate, max_generation_calls=limit))
    with pytest.raises(GenerationWorkLimitError):
        run("test", generate, 6)
    assert calls == ["adapt.narrative_treatment", "adapt.blueprint", "adapt.lettering",
                     "adapt.narrative_review", "adapt.narrative_review", "adapt.book"]
    saved = target.read_failed_adaptation_candidate()
    assert saved.beats[0].lettering[0].text == improved
    assert not target.adaptation_path.exists()
    calls.clear()
    for _ in range(2):
        with pytest.raises(GenerationWorkLimitError):
            run("other", generate)
        assert calls == []
        assert target.read_failed_adaptation_candidate() == saved
    work = _resume_adaptation_work(source, bible, brief, artifacts=target, model="other", instruction="")
    assert work.candidate == saved
    assert work.pending_repair.model == "test"
    assert _resume_adaptation_work(source, bible.model_copy(update={"title": "Changed authority"}),
        brief, artifacts=target, model="other", instruction="") is None
    assert _resume_adaptation_work(source, bible, brief, artifacts=target,
        model="other", instruction="Changed intent") is None
    import novel_to_comic.book_adaptation as module
    def unexpected_initial_prompt(*args, **kwargs):
        raise AssertionError("Resume estimate must not include initial story generation")
    monkeypatch.setattr(module, "build_adaptation_blueprint_prompt", unexpected_initial_prompt)
    monkeypatch.setattr(module, "build_locked_lettering_prompt", unexpected_initial_prompt)
    assert module.estimate_book_adaptation_cost(source, bible, brief, artifacts=target, model="other") >= 0
    async def fresh_review(**request):
        calls.append(request["feature"])
        assert request["feature"] == "adapt.narrative_review"
        assert improved in request["user_content"]
        return ApiResult(value=verdict(request))
    # Only an explicit limit change admits the remaining review; no regeneration.
    result = run("other", fresh_review, 7)
    assert result.beats[0].lettering[0].text == improved
    assert calls == ["adapt.narrative_review"]
    assert target.read_narrative_review("adapt").model == "other"
    budget = json.loads(next((tmp_path / ".checkpoints/adapt/work").glob("*.json")).read_text())
    assert len(budget["calls"]) == budget["limit"] == 7


def test_reviewed_candidate_without_current_work_receipts_is_not_adopted(tmp_path):
    from novel_to_comic.book_adaptation import _reviewed_candidate_for_resume
    a = _book_adaptation()
    target = TargetArtifacts(tmp_path)
    target.write_failed_adaptation_candidate(a)
    context = adaptation_context(_source_document(), _approved_brief(), a)
    async def generate(**request):
        return ApiResult(value=verdict(request))
    asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
                                 artifacts=target, model="test"))
    # Review freshness alone cannot bind a changed Story Bible or prove which
    # stage input lineage paid for the current candidate.
    assert _reviewed_candidate_for_resume(_source_document(), _story_bible(), _approved_brief(),
                                          artifacts=target, model="test") is None


def test_page_map_review_counts_assigned_words_before_panel_detail_exists():
    adaptation = _long_adaptation(2)
    page_map = [
        {"page_number": 1, "beat_ids": [adaptation.beats[0].id],
         "lettering_ids": [adaptation.beats[0].lettering[0].id], "rhythm_intent": "Narrated event."},
        {"page_number": 2, "beat_ids": [adaptation.beats[0].id],
         "lettering_ids": [], "rhythm_intent": "A silent detail of that event."},
        {"page_number": 3, "beat_ids": [adaptation.beats[1].id],
         "lettering_ids": [adaptation.beats[1].lettering[0].id], "rhythm_intent": "The next event."},
    ]
    from novel_to_comic.page_planning import _PageMapEntry
    mapped = [_PageMapEntry.model_validate({**page, "emphasis": "initial", "density_intent": "standard"}) for page in page_map]
    prompt = next(iter(_review_prompts(planning_context(adaptation, mapped, phase="plan_map"))))
    context = json.loads(prompt.split("\n", 1)[1])
    assert [page["narrative_words"] for page in context["global_pages"]] == [2, 0, 2]
    assert "without demanding panel placement" in prompt


def test_empty_signal_window_corrects_invented_checks_without_losing_findings(tmp_path):
    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    assert not narrative_signals(context)
    finding = {"code": "missing_context", "repair_stage": "adapt", "artifact_ids": ["beat_0001"],
               "evidence": "A speaker label contradicts its entity attribution.",
               "repair": "Correct the entity attribution while retaining the words."}
    calls = []
    async def generate(**request):
        calls.append(request)
        assert request["json_schema"]["properties"]["signal_assessments"]["maxItems"] == 0
        value = verdict(request, finding=finding)
        if len(calls) == 1:
            value["signal_assessments"] = [
                {"signal_id": name, "acceptable": True, "evidence": "The beat is accounted for."}
                for name in ("beats[beat_0001]", "ledger")
            ]
        elif len(calls) == 2:
            assert "unexpected signal IDs" in request["user_content"]
            assert "No signals were requested" in request["user_content"]
            assert finding["evidence"] in request["user_content"]
        return ApiResult(value=value)
    target = TargetArtifacts(tmp_path)
    async def run():
        return await review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
                                      artifacts=target, model="test")
    failures = asyncio.run(run())
    assert [failure.code for failure in failures] == ["narrative_review_missing_context"]
    assert failures[0].evidence[0] == finding["evidence"]
    assert len(calls) == 3
    assert asyncio.run(run()) == failures
    assert len(calls) == 3  # Base, protocol correction and confirmation are exact-input cached.


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "invented"])
def test_signal_protocol_correction_preserves_negative_judgments(tmp_path, invalid):
    adaptation = _long_adaptation(2)
    context = planning_context(adaptation, canonical(adaptation, draft_for(adaptation, padding=4)))
    calls = []
    async def generate(**request):
        calls.append(request)
        value = verdict(request, accept=False)
        assert len(value["signal_assessments"]) == 2
        if len(calls) == 1:
            if invalid == "missing":
                value["signal_assessments"].pop()
            elif invalid == "duplicate":
                value["signal_assessments"][1] = dict(value["signal_assessments"][0])
            else:
                value["signal_assessments"][1]["signal_id"] = "invented"
        else:
            assert "VALIDATION ERRORS" in request["user_content"]
            assert "Preserve supported findings and editorial judgments" in request["user_content"]
        return ApiResult(value=value)
    target = TargetArtifacts(tmp_path)
    failures = asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "plan"),
                                            artifacts=target, model="test"))
    assert len(calls) == 2
    assert not failures
    assert len(TargetArtifacts(tmp_path).read_narrative_review("plan").editorial_issues) == 2
    assert all(not assessment.acceptable for verdict_ in target.read_narrative_review("plan").verdicts
               for assessment in verdict_.signal_assessments)


def test_review_protocol_correction_cannot_bypass_cumulative_request_limit(tmp_path):
    from novel_to_comic.generation_budget import budgeted_generator, GenerationWorkLimitError
    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    calls = []
    async def invalid(**request):
        calls.append(request)
        return ApiResult(value={"wrong": True})
    target = TargetArtifacts(tmp_path)
    generate = budgeted_generator(invalid, artifacts=target, stage="adapt", model="test", inputs=context, max_calls=1)
    with pytest.raises(GenerationWorkLimitError):
        asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
                                    artifacts=target, model="test"))
    assert len(calls) == 1


def test_review_windows_overlap_in_time_but_publish_in_order_and_resume_from_cache(tmp_path):
    async def scenario():
        adaptation = _long_adaptation(30)
        context = planning_context(adaptation, canonical(adaptation, draft_for(adaptation)))
        target = TargetArtifacts(tmp_path)
        starts, finished = [], []
        all_started = asyncio.Event()
        gates = {1: asyncio.Event(), 13: asyncio.Event()}

        async def generate(**request):
            supplied = json.JSONDecoder().raw_decode(request['user_content'].split('\n', 1)[1])[0]
            first_page = supplied['pages'][0]['page_number']
            starts.append(first_page)
            if len(starts) == 3:
                all_started.set()
            await all_started.wait()
            if first_page in gates:
                await gates[first_page].wait()
            finished.append(first_page)
            if first_page == 25:
                gates[13].set()
            elif first_page == 13:
                gates[1].set()
            return ApiResult(value=verdict(request, finding={
                'code': 'rushed_sequence', 'repair_stage': 'plan',
                'artifact_ids': [f'page_{first_page:03d}'],
                'evidence': 'An optional longer pause.', 'repair': 'Consider a quieter composition.',
            }))

        result = await asyncio.wait_for(review_narrative(
            context, generate=generate, ctx=runtime(tmp_path, 'plan'), artifacts=target, model='test',
        ), timeout=2)
        assert not result
        assert starts == [1, 13, 25]
        assert finished == [25, 13, 1]
        assert [i.artifact_ids[0] for i in target.read_narrative_review('plan').editorial_issues] == [
            'page_001', 'page_013', 'page_025']
        await review_narrative(context, generate=generate, ctx=runtime(tmp_path, 'plan'),
                              artifacts=target, model='test')
        assert len(starts) == 3

    asyncio.run(scenario())


def test_parallel_invalid_reviews_retain_all_completed_siblings_for_resume(tmp_path):
    async def scenario():
        adaptation = _long_adaptation(30)
        context = planning_context(adaptation, canonical(adaptation, draft_for(adaptation)))
        target = TargetArtifacts(tmp_path)
        started = set()
        all_started = asyncio.Event()

        async def first(**request):
            supplied = json.JSONDecoder().raw_decode(request['user_content'].split('\n', 1)[1])[0]
            page = supplied['pages'][0]['page_number']
            started.add(page)
            if len(started) == 3:
                all_started.set()
            await all_started.wait()
            return ApiResult(value={'wrong': True} if page in {1, 13} else verdict(request))

        failures = await asyncio.wait_for(review_narrative(
            context, generate=first, ctx=runtime(tmp_path, 'plan'), artifacts=target, model='test',
        ), timeout=2)
        assert [f.id for f in failures] == ['plan_review_invalid_1', 'plan_review_invalid_2']
        calls = []

        async def corrected(**request):
            calls.append(request)
            return ApiResult(value=verdict(request))

        failures = await review_narrative(context, generate=corrected, ctx=runtime(tmp_path, 'plan'),
                                         artifacts=target, model='test')
        assert not failures
        assert len(calls) == 2
        assert all('Recheck the malformed prior review' in c['user_content'] for c in calls)

    asyncio.run(scenario())


def test_canonical_staging_can_substantiate_a_continuity_contradiction():
    from novel_to_comic.narrative_review import _blocks
    window = {
        "beats": [{"id": "beat_15", "summary": "He remains pinned against the testing room wall.", "lettering": []}],
        "pages": [{"page_number": 7, "layout_intent": "The body rests on a mop head in the closet.", "content": []}],
    }
    finding = NarrativeFinding(
        code="unsupported_event", repair_stage="plan", artifact_ids=("beat_15", "page_007"),
        evidence="Staging moves the body into the closet and changes its support.",
        repair="Keep the established room and shaft attachment.", consequence="contradiction",
        reader_impact="The aftermath no longer follows the preceding action.",
        passages=(NarrativePassage(artifact_id="beat_15", quote=window["beats"][0]["summary"]),
                  NarrativePassage(artifact_id="page_007", quote=window["pages"][0]["layout_intent"])),
    )
    assert _blocks(finding, window, "plan")
    invented = finding.model_copy(update={"passages": (finding.passages[0],
        NarrativePassage(artifact_id="page_007", quote="This text was not supplied."))})
    assert not _blocks(invented, window, "plan")


def test_plan_signals_an_exchange_staged_in_a_faceless_insert():
    def line(speaker):
        return {"kind": "dialogue", "delivery": "onscreen", "speaker_entity_id": speaker}

    page = {"page_number": 10, "beat_ids": ["beat_1"], "content": [
        {"id": "page_010_content_003", "beat_ids": ["beat_1"], "camera": {"shot": "insert"},
         "lettering": [line("char_witch"), line("char_oran"), line("char_witch")]},
        {"id": "page_010_content_004", "beat_ids": ["beat_1"], "camera": {"shot": "medium"},
         "lettering": [line("char_witch"), line("char_oran")]},
    ]}
    context = {"phase": "plan", "beats": [], "pages": [page]}

    signals = [s for s in narrative_signals(context) if s["id"].startswith("faceless_exchange")]

    assert [s["id"] for s in signals] == ["faceless_exchange_page_010_content_003"]
    assert signals[0]["artifact_ids"] == ["page_010"]
