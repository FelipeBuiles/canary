"""Provider-free editorial review, repair, freshness and admission regressions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import pytest

from novel_to_comic.narrative_review import (
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


def draft_for(adaptation, padding=0):
    beats = list(adaptation.beats) + [adaptation.beats[-1]] * padding
    return {
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
                        "visual_intent": b.summary,
                        "lettering_ids": [i.id for i in b.lettering]
                        if n <= len(adaptation.beats)
                        else [],
                    }
                ],
            }
            for n, b in enumerate(beats, 1)
        ],
    }


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


def test_plan_repairs_structure_and_can_finish_below_target(tmp_path):
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
    assert len(plan.pages) == 22
    assert plan.target_page_min == 34
    assert book_calls == 2
    assert target.read_validation("plan").attempt_history[0].invariant_codes
    require_narrative_review(
        target, "plan", planning_context(a, [target.read_page(n) for n in range(1, 23)])
    )


def test_persistent_padding_never_publishes_a_plan(tmp_path):
    a = _long_adaptation(22)

    async def generate(**request):
        if request["feature"] == "plan.book":
            return ApiResult(value=draft_for(a, 12))
        return ApiResult(value=verdict(request, accept=False))

    target = TargetArtifacts(tmp_path)
    with pytest.raises(PlanInvariantError):
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
    assert not target.plan_path.exists()
    assert target.read_validation("plan").blocked


def test_map_review_repairs_global_padding_before_detail_spend(tmp_path):
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
            assert maps == 2
            context = json.JSONDecoder().raw_decode(
                request["user_content"].split("\n", 1)[1]
            )[0]
            numbers = context["target_page_numbers"]
            raw = draft_for(a)
            return ApiResult(
                value={
                    **raw,
                    "pages": [p for p in raw["pages"] if p["page_number"] in numbers],
                }
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
    assert len(plan.pages) == 24 and maps == 2 and details >= 3


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
    with pytest.raises(ValueError, match="Rerun Adapt"):
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


def test_plan_defect_owned_by_adapt_does_not_trigger_useless_replanning(tmp_path):
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

    with pytest.raises(PlanInvariantError) as error:
        asyncio.run(
            produce_book_plan(
                a,
                _inventory(),
                ApprovedPageRange(minimum=1, maximum=4),
                artifacts=TargetArtifacts(tmp_path),
                ctx=runtime(tmp_path, "plan"),
                model="test",
                generate=generate,
            )
        )
    assert book_calls == 1
    assert error.value.validation.invariant_failures[0].owner_stage == "adapt"


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


def test_final_two_pass_review_can_rebuild_global_map(tmp_path):
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
                value={
                    **raw,
                    "pages": [
                        p
                        for p in raw["pages"]
                        if p["page_number"] in supplied["target_page_numbers"]
                    ],
                }
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
    assert maps == 2 and len(plan.pages) == 23
    assert any(
        "narrative_review_padding" in a.invariant_codes
        for a in target.read_validation("plan").attempt_history
    )
