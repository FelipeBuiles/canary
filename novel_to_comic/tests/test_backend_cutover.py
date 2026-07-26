"""Ticket 07: active backend cutover to the eight-stage page pipeline."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from novel_to_comic.stages import REGISTRY, clean_cascade
from novel_to_comic.server.routers import pipeline
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.server import credits
from novel_to_comic.state import (
    CHECKPOINT_STAGES,
    STAGE_NAMES,
    PipelineState,
    create_initial_state,
    StageStatus,
)


TARGET_STAGES = [
    "extract",
    "brief",
    "style",
    "cast",
    "adapt",
    "plan",
    "draw",
    "finish",
]


def test_active_pipeline_contains_exactly_the_eight_target_stages() -> None:
    state = create_initial_state("book", "input/book.txt")

    assert STAGE_NAMES == TARGET_STAGES
    assert list(REGISTRY) == TARGET_STAGES
    assert list(state.stages) == TARGET_STAGES
    assert CHECKPOINT_STAGES == {"brief", "style", "cast", "draw"}


@pytest.mark.parametrize("old_stage", ["storyboard", "direct", "compose"])
def test_old_stage_state_is_rejected(old_stage: str) -> None:
    state = create_initial_state("book", "input/book.txt").model_dump(mode="json")
    state["stages"][old_stage] = {}

    with pytest.raises(ValidationError, match="unknown pipeline stages"):
        PipelineState.model_validate_json(json.dumps(state))


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (
            "source",
            ["source", "brief", "samples", "refs", "plates", "adapt", "plan", "draw", "finish", "exports"],
        ),
        (
            "brief",
            ["brief", "samples", "refs", "plates", "adapt", "plan", "draw", "finish", "exports"],
        ),
        ("adapt", ["adapt", "plan", "draw", "finish", "exports"]),
        ("plan", ["plan", "draw", "finish", "exports"]),
        ("draw", ["draw", "finish", "exports"]),
        ("finish", ["finish", "exports"]),
    ],
)
def test_clean_cascade_uses_only_target_artifact_roots(
    tmp_path, start: str, expected: list[str]
) -> None:
    assert clean_cascade(tmp_path, start) == [tmp_path / name for name in expected]


def test_auto_chain_stops_at_brief_review_and_before_draw() -> None:
    assert pipeline.STAGE_AUTO_CHAIN == {
        "extract": ["brief"],
        "adapt": ["plan"],
    }


@pytest.mark.parametrize(
    ("rerun", "reset"),
    [
        ("extract", set(TARGET_STAGES)),
        ("brief", {"brief", "adapt", "plan", "draw", "finish"}),
        ("style", {"style", "cast", "adapt", "plan", "draw", "finish"}),
        ("cast", {"cast", "adapt", "plan", "draw", "finish"}),
        ("adapt", {"adapt", "plan", "draw", "finish"}),
        ("plan", {"plan", "draw", "finish"}),
        ("draw", {"draw", "finish"}),
        ("finish", {"finish"}),
    ],
)
def test_rerun_resets_exact_target_dependency_graph(rerun: str, reset: set[str]) -> None:
    state = create_initial_state("book", "input/book.txt")
    for stage in TARGET_STAGES:
        state.stages[stage].status = StageStatus.COMPLETE

    pipeline._reset_stage_and_downstream(state, rerun)

    assert {
        stage
        for stage, stage_state in state.stages.items()
        if stage_state.status == StageStatus.PENDING
    } == reset


def test_rerun_removes_only_the_stage_target_artifacts_and_dependants(tmp_path) -> None:
    for root in ("source", "brief", "samples", "refs", "plates", "adapt", "plan", "draw", "finish", "exports"):
        directory = tmp_path / root
        directory.mkdir()
        (directory / "marker").write_text(root)

    pipeline._clear_outputs_for_rerun(tmp_path, "plan")

    assert all((tmp_path / root / "marker").exists() for root in ("source", "brief", "samples", "refs", "plates", "adapt"))
    assert all(not (tmp_path / root).exists() for root in ("plan", "draw", "finish", "exports"))


@pytest.mark.parametrize("old_stage", ["storyboard", "direct", "compose"])
def test_old_stage_routes_are_not_registered(old_stage: str) -> None:
    paths = {route.path for route in pipeline.router.routes}
    assert all(old_stage not in path for path in paths)


def test_draw_runtime_emits_complete_page_events(tmp_path) -> None:
    events = []
    runtime = StageRuntime(
        "draw",
        create_initial_state("book", "input/book.txt"),
        tmp_path,
        on_event=events.append,
    )

    runtime.emit_page_start(7)
    runtime.emit_page_done(7, revision=2, status="ok", duration_ms=1200)

    assert [event["type"] for event in events] == ["page_start", "page_done"]
    assert events[0]["page_number"] == 7
    assert events[1] == {
        "type": "page_done",
        "stage": "draw",
        "page_number": 7,
        "revision": 2,
        "status": "ok",
        "duration_ms": 1200,
        "error": None,
    }
    assert not hasattr(runtime, "emit_panel_start")


def test_credit_confidence_recognizes_only_target_stage_names() -> None:
    assert {
        stage: credits.stage_cost_confidence(stage) for stage in TARGET_STAGES
    } == {
        "extract": "usually_within_estimate",
        "brief": "usually_within_estimate",
        "style": "usually_within_estimate",
        "cast": "variable",
        "adapt": "usually_within_estimate",
        "plan": "usually_within_estimate",
        "draw": "variable",
        "finish": "low_variance",
    }
    assert not hasattr(credits.UnifiedCostResolver, "estimate_panel_regen_cost")
