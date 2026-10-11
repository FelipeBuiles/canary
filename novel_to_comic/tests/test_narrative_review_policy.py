"""Review preferences cannot acquire blocking authority without cited harm."""

import asyncio
from copy import deepcopy

import pytest

from novel_to_comic.narrative_review import adaptation_context, review_narrative, require_narrative_review
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult
from .test_book_adaptation import _source_document, _approved_brief, _book_adaptation
from .test_narrative_review import runtime


@pytest.mark.parametrize("change,blocking", [
    ("valid", True), ("padding", False), ("rushed_sequence", False), ("redundant_caption", False),
    ("unquoted", False), ("fabricated_quote", False), ("misattributed_quote", False),
    ("no_impact", False), ("preference", False), ("missing_requirement", False),
])
def test_review_blocking_threshold_is_enforced_by_code(tmp_path, change, blocking):
    source, brief, adaptation = _source_document(), _approved_brief(), _book_adaptation()
    context = adaptation_context(source, brief, adaptation)
    context["units"][0]["text"] = "The narrator learned about the door later; he did not witness it opening."
    item = adaptation.beats[0].lettering[0]
    finding = {
        "code": "unsupported_event", "repair_stage": "adapt",
        "artifact_ids": [item.id, source.units[0].id],
        "evidence": "The depicted event contradicts the cited source account.",
        "repair": "Restore the sequence established by the source.",
        "consequence": "contradiction",
        "reader_impact": "The reader would understand the protagonist to have witnessed an event he only heard about.",
        "passages": [{"artifact_id": item.id, "quote": item.text},
                     {"artifact_id": source.units[0].id, "quote": context["units"][0]["text"]}],
    }
    if change in {"padding", "rushed_sequence", "redundant_caption"}:
        finding["code"] = change  # Even a claimed severe consequence cannot promote pacing.
    elif change == "unquoted":
        finding["passages"] = []
    elif change == "fabricated_quote":
        finding["passages"][0]["quote"] = "Words that never appeared in the draft."
    elif change == "misattributed_quote":
        finding["passages"][0]["quote"] = context["units"][0]["text"]
    elif change == "no_impact":
        finding["reader_impact"] = ""
    elif change == "preference":
        finding["consequence"] = "editorial_preference"
    elif change == "missing_requirement":
        finding["consequence"] = "explicit_requirement_violation"
    original = deepcopy(finding)
    calls = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value={"findings": [finding], "signal_assessments": []})

    target = TargetArtifacts(tmp_path)
    failures = asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
                                          artifacts=target, model="test"))
    assert len(calls) == 1  # Weak criticism does not spend another review or authoring call.
    assert bool(failures) is blocking
    record = target.read_narrative_review("adapt")
    assert bool(record.editorial_issues) is not blocking
    assert finding == original
    if blocking:
        with pytest.raises(ValueError, match="failed or stale"):
            require_narrative_review(target, "adapt", context)
    else:
        require_narrative_review(target, "adapt", context)
        assert not record.editorial_issues[0].blocking


@pytest.mark.parametrize("stale", [False, True])
def test_saved_plan_review_draft_is_inspectable_but_not_canonical(tmp_path, stale):
    from fastapi import HTTPException
    from novel_to_comic.models.page import PlanReviewDraft
    from novel_to_comic.server.routers.stages import get_plan_review_draft
    from .test_narrative_review import canonical, draft_for
    from .test_page_planning import _long_adaptation

    adaptation = _long_adaptation(2)
    target = TargetArtifacts(tmp_path)
    target.write_adaptation(adaptation)
    draft = PlanReviewDraft(adaptation_sha256="f" * 64 if stale else adaptation.content_sha256,
                            rhythm_summary="Awaiting review.", pages=canonical(adaptation, draft_for(adaptation)))
    target.write_plan_review_draft(draft)
    if stale:
        with pytest.raises(HTTPException) as error:
            get_plan_review_draft((tmp_path, None, None))
        assert error.value.status_code == 409
    else:
        assert get_plan_review_draft((tmp_path, None, None)) == draft
    assert not target.plan_path.exists()


@pytest.mark.parametrize("outcome", ["pass", "block", "source_changed", "already_current"])
def test_resume_published_adaptation_refreshes_only_review(tmp_path, outcome):
    from novel_to_comic.book_adaptation import (
        AdaptationInvariantError, _canonicalize_candidate_requirements,
        produce_book_adaptation, validate_book_adaptation,
    )
    from novel_to_comic.narrative_review import NarrativeReviewRecord, REVIEW_VERSION, review_digest
    from .test_book_adaptation import _story_bible
    from .test_narrative_review import verdict

    source, brief, bible = _source_document(), _approved_brief(), _story_bible()
    adaptation = _canonicalize_candidate_requirements(_book_adaptation(), source, brief, story_bible=bible)
    assert not validate_book_adaptation(source, brief, adaptation, story_bible=bible).invariant_failures
    target = TargetArtifacts(tmp_path)
    target.write_adaptation(adaptation)
    original = target.adaptation_path.read_bytes()
    checkpoint = tmp_path / ".checkpoints" / "plan" / "saved.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text('{"saved":true}')
    context = adaptation_context(source, brief, adaptation)
    target.write_narrative_review("adapt", NarrativeReviewRecord(
        version=REVIEW_VERSION if outcome == "already_current" else "narrative_v3",
        input_sha256=review_digest(context), model="test", instruction="",
        verdicts=({"findings": [], "signal_assessments": []},), failures=(),
    ))
    if outcome == "source_changed":
        source = source.model_copy(update={"source_sha256": "f" * 64})
    calls = []

    async def generate(**request):
        calls.append(request["feature"])
        assert request["feature"] == "adapt.narrative_review"
        finding = None if outcome != "block" else {
            "code": "missing_context", "repair_stage": "adapt",
            "artifact_ids": [adaptation.beats[0].id],
            "evidence": "The actor is not established, so the event is unintelligible.",
            "repair": "Establish the actor.",
        }
        return ApiResult(value=verdict(request, finding=finding))

    def resume():
        return asyncio.run(produce_book_adaptation(
            source, bible, brief, artifacts=target, ctx=runtime(tmp_path, "adapt"),
            model="test", generate=generate,
        ))

    if outcome in {"block", "source_changed"}:
        with pytest.raises(AdaptationInvariantError):
            resume()
    else:
        assert resume() == adaptation
        require_narrative_review(target, "adapt", context)
    assert len(calls) == (0 if outcome in {"source_changed", "already_current"} else 2 if outcome == "block" else 1)
    assert target.adaptation_path.read_bytes() == original
    assert checkpoint.read_text() == '{"saved":true}'
    assert not target.failed_adaptation_candidate_path.exists()


@pytest.mark.parametrize("outcome", ["withdraw", "confirm", "invalid", "transport"])
@pytest.mark.parametrize("other_defect", [False, True])
def test_missing_context_is_verified_before_story_repair(tmp_path, outcome, other_defect):
    """A reviewer can overlook exactly the caption it asks the author to add."""
    from novel_to_comic.narrative_review import _review_contexts, _substantiated_blocker, NarrativeFinding

    context = adaptation_context(_source_document(), _approved_brief(), _book_adaptation())
    beat = context["beats"][0]
    item = beat["lettering"][0]
    item["text"] = "I couldn’t understand the goblin language. It was grunts and squeaks."
    missing = {
        "code": "missing_context", "repair_stage": "adapt", "artifact_ids": [item["id"]],
        "evidence": "The goblin language has not been established.",
        "repair": "Explain that Carl cannot understand the goblin language.",
        "consequence": "unintelligible_sequence", "reader_impact": "The exchange has no context.",
        "passages": [{"artifact_id": item["id"], "quote": item["text"]}],
    }
    # Keep an independently blocking defect even if confirmation drops it.
    other = {**missing, "code": "unsupported_event", "evidence": "A separate event is unsupported."}
    window = next(_review_contexts(context))
    assert _substantiated_blocker(NarrativeFinding.model_validate(other), window)
    calls = []

    async def generate(**request):
        calls.append(request)
        if len(calls) == 1:
            return ApiResult(value={"findings": [missing, other] if other_defect else [missing], "signal_assessments": []})
        assert "VERIFY MISSING CONTEXT BEFORE REPAIR" in request["user_content"]
        assert item["text"] in request["user_content"]
        if outcome == "transport":
            raise TimeoutError("confirmation interrupted")
        if outcome == "invalid":
            return ApiResult(value={"findings": [], "signal_assessments": [
                {"signal_id": "invented", "acceptable": True, "evidence": "Not supplied."},
            ]})
        return ApiResult(value={"findings": [missing] if outcome == "confirm" else [],
                                "signal_assessments": []})

    target = TargetArtifacts(tmp_path)
    def run():
        return asyncio.run(review_narrative(context, generate=generate, ctx=runtime(tmp_path, "adapt"),
                                           artifacts=target, model="test"))
    if outcome == "transport":
        with pytest.raises(TimeoutError):
            run()
        with pytest.raises(ValueError):
            require_narrative_review(target, "adapt", context)
        assert len(calls) == 2
        return
    failures = run()
    codes = {f.code for f in failures}
    if outcome == "invalid":
        assert codes == {"narrative_review_invalid"}
        assert len(calls) == 3
    else:
        expected = {"narrative_review_unsupported_event"} if other_defect else set()
        if outcome == "confirm":
            expected.add("narrative_review_missing_context")
        assert codes == expected
        if not expected:
            require_narrative_review(target, "adapt", context)
        assert len(calls) == 2
        assert run() == failures
        assert len(calls) == 2  # Both verdicts reuse their exact-input checkpoints.
