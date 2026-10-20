"""Policy tables and clean-candidate review through the validation interface."""
import asyncio

import pytest

from novel_to_comic.book_adaptation import AdaptationValidation
from novel_to_comic.models.validation import InvariantFailure, ValidationAttempt
from novel_to_comic.page_planning import PlanValidation
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.validation_round import (
    PlanRepairPolicy, adapt_repair_allowed, persist_validation,
    record_validation_attempt, review_clean_candidate,
)


def failure(code, owner="plan", artifact="page_001"):
    return InvariantFailure(id=code, owner_stage=owner, code=code, message="Blocking defect",
                            evidence=("Exact evidence",), artifact_ids=(artifact,))


@pytest.mark.parametrize("kind", [AdaptationValidation, PlanValidation])
def test_dirty_candidate_never_reaches_paid_review(kind):
    validation = kind(invariant_failures=(failure("structural"),))

    async def forbidden(*args, **kwargs):
        pytest.fail("structurally invalid candidate reached review")

    assert asyncio.run(review_clean_candidate(
        validation, {"phase": "plan"}, generate=forbidden, ctx=None, artifacts=None,
        model="test", reviewer=forbidden,
    )) is validation


def test_round_merges_and_persists_complete_review_history(tmp_path):
    target = TargetArtifacts(tmp_path)
    blocker = failure("target_page_range_conflict")

    async def reviewer(context, **kwargs):
        assert context == {"phase": "plan"}
        return (blocker,)

    verdict = asyncio.run(review_clean_candidate(
        PlanValidation(), {"phase": "plan"}, generate=None, ctx=None, artifacts=target,
        model="test", reviewer=reviewer,
    ))
    history = (record_validation_attempt(1, verdict),)
    persist_validation("plan", target, verdict, attempts=1, history=history)
    saved = target.read_validation("plan")
    assert saved.invariant_failures == (blocker,)
    assert saved.recommendations == ("Exact evidence",)
    assert saved.attempt_history == history


@pytest.mark.parametrize("previous,current,allowed", [
    (("structure",), ("structure",), False),
    (("structure", "other"), ("structure",), True),
    (("structure",), ("other",), False),
    (("structure",), ("narrative_review_gap",), True),
    (("narrative_review_gap",), ("structure",), True),
    (("narrative_review_gap",), ("narrative_review_invalid",), False),
])
def test_adapt_keeps_its_progress_sensitive_final_repair(previous, current, allowed):
    history = [ValidationAttempt(attempt=1, invariant_codes=previous),
               ValidationAttempt(attempt=2, invariant_codes=current)]
    assert adapt_repair_allowed(2, history) is allowed
    assert not adapt_repair_allowed(3, history)


def test_plan_repairs_structure_and_narrative_once_each():
    policy = PlanRepairPolicy()
    structure, review = failure("structure"), failure("narrative_review_gap")
    unfixable = (failure("narrative_review_invalid"), failure("brief_contract", owner="brief"))
    assert policy.eligible((structure, *unfixable)) == (structure,)
    policy.repaired((structure,))
    assert policy.eligible((structure, review, *unfixable)) == (review,)
    policy.repaired((review,))
    assert policy.eligible((structure, review)) == ()
    resumed = PlanRepairPolicy.from_history([ValidationAttempt(attempt=1, invariant_codes=(review.code,))])
    assert resumed.eligible((review, structure)) == (structure,)


@pytest.mark.parametrize("owners,allow_mixed,expected", [
    (("plan",), False, True), (("adapt",), False, False),
    (("plan", "adapt"), False, False), (("plan", "adapt"), True, True),
    ((), True, False),
])
def test_plan_map_and_one_shot_retain_their_existing_owner_rules(owners, allow_mixed, expected):
    failures = tuple(failure("structure", owner) for owner in owners)
    assert PlanRepairPolicy.may_retry(failures, allow_mixed_owners=allow_mixed) is expected
    assert not PlanRepairPolicy.may_retry((*failures, failure("narrative_review_invalid")),
                                          allow_mixed_owners=allow_mixed)
