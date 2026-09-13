"""Focused behavior tests for the editorial/story-change backend slice.

Covers: on-demand source excerpts, revision-scoped keep/reopen decisions
(including resurfacing of changed evidence), non-destructive preview with
truthful cascade impact, reload persistence, and the apply guards
(stale/apply-twice/running) plus the real orchestration handoff.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from novel_to_comic.artifacts import write_story_bible
from novel_to_comic.config import Config
from novel_to_comic.editorial import (
    StoryChangeDirective,
    StoryDirectiveError,
    load_story_directive,
    mark_story_change_applied,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import s4_adapt, s5_plan
from novel_to_comic.models.adaptation import (
    AdaptedBeat,
    AdaptationBrief,
    AdaptationLedgerEntry,
    BookAdaptation,
    NarrativeTreatment,
)
from novel_to_comic.models.page import (
    BookPlan,
    ComicPage,
    PageContent,
    PlannedPageRevision,
)
from novel_to_comic.models.story_bible import Scene, StoryBible
from novel_to_comic.models.validation import EditorialIssue
from novel_to_comic.server.app import create_app
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.source_extraction import produce_source_document
from novel_to_comic.state import PipelineState, save_state
from novel_to_comic.target_artifacts import TargetArtifacts


def _make_state() -> PipelineState:
    return PipelineState(
        project_name="Test Project",
        novel_path="input/test.txt",
        created_at="2026-01-01T00:00:00Z",
    )


def _anchor_scene(scene_id: str, title: str, quote: str) -> Scene:
    return Scene(
        id=scene_id,
        chapter=1,
        title=title,
        location_id="location_room",
        character_ids=[],
        summary="A scene.",
        scene_type="action",
        narrative_beat="initial",
        source_start_quote=quote,
    )


def _story_project(tmp_path: Path) -> tuple[Path, PipelineState]:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    state = _make_state()
    save_state(state, project_dir)
    target = TargetArtifacts(project_dir)
    bible = StoryBible(
        title="The Door",
        author="A. Writer",
        total_scenes=2,
        characters=[],
        locations=[],
        narrative_arcs=[],
        scenes=[
            _anchor_scene("scene_001", "The door", "The door opened."),
            _anchor_scene("scene_002", "Silence", "Nothing moved."),
        ],
    )
    write_story_bible(project_dir, bible)
    source = produce_source_document(
        target,
        "The door opened. A light burned. Nothing moved.",
        bible,
    )
    brief = AdaptationBrief(
        revision=1,
        status="approved",
        story_promises=("The door matters.",),
        themes=("Thresholds.",),
        point_of_view="Third person.",
        narrator_treatment="Quiet observer.",
        tone="Tense.",
        essential_events=("The door opens.",),
        character_turns=("Ana decides.",),
        desired_emphasis=("The door.",),
        target_page_min=1,
        target_page_max=4,
    )
    target.write_brief(brief)
    first_unit = source.units[0].id
    adaptation = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=brief.revision,
        brief_sha256=brief.content_sha256,
        treatment=NarrativeTreatment(causal_spine=("A door opens.",)),
        beats=(
            AdaptedBeat(
                id="beat_0001",
                order=1,
                summary="The door opens.",
                narrative_function="establisher",
                source_unit_ids=(first_unit,),
            ),
        ),
        ledger=tuple(
            AdaptationLedgerEntry(
                source_unit_id=unit.id,
                disposition="depicted",
                adapted_beat_ids=("beat_0001",),
                preserved_function="Threshold crossed.",
            )
            for unit in source.units
        ),
        editorial_issues=(
            EditorialIssue(
                id="adapt_issue_001",
                owner_stage="adapt",
                code="rushed_aftermath",
                message="The aftermath beat is missing.",
                source_unit_ids=(first_unit,),
                artifact_ids=("beat_0001",),
                evidence=("Beat 0001 ends at the peak with no release.",),
            ),
        ),
    )
    target.write_adaptation(adaptation)
    page = ComicPage(
        revision=1,
        page_number=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        emphasis="establisher",
        density_intent="standard",
        content=(
            PageContent(
                id="c001",
                order=1,
                beat_ids=("beat_0001",),
                visual_intent="The door swings open.",
            ),
        ),
        reading_order=("c001",),
    )
    target.write_page(page)
    target.write_plan(
        BookPlan(
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            target_page_min=1,
            target_page_max=4,
            pages=(
                PlannedPageRevision(
                    page_number=1,
                    revision=page.revision,
                    content_sha256=page.content_sha256,
                ),
            ),
            editorial_issues=(
                EditorialIssue(
                    id="plan_issue_001",
                    owner_stage="plan",
                    code="weak_page_turn",
                    message="Page one ends without a turn.",
                    artifact_ids=("beat_0001", "page_001"),
                    evidence=("The reveal lands mid-page.",),
                ),
            ),
        )
    )
    return project_dir, state


def _client(
    tmp_path: Path, project_dir: Path, state: PipelineState
) -> TestClient:
    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    client = TestClient(app)
    client.event_hooks["request"].append(
        lambda request: request.headers.setdefault("Idempotency-Key", str(uuid4()))
    )
    return client


def test_editorial_get_exposes_findings_with_source_beat_links(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)

    res = client.get("/api/projects/test_project/editorial")
    assert res.status_code == 200
    body = res.json()
    assert body["revision"].startswith("adapt=1:")
    by_id = {item["issue_id"]: item for item in body["decisions"]}
    assert set(by_id) == {"adapt_issue_001", "plan_issue_001"}
    assert by_id["adapt_issue_001"]["disposition"] == "open"
    assert by_id["adapt_issue_001"]["owner_stage"] == "adapt"
    assert by_id["adapt_issue_001"]["source_unit_ids"] == [
        TargetArtifacts(project_dir).read_source().units[0].id
    ]
    assert by_id["adapt_issue_001"]["artifact_ids"] == ["beat_0001"]
    assert by_id["plan_issue_001"]["artifact_ids"] == ["beat_0001", "page_001"]
    assert body["story_changes"] == []


def test_source_excerpts_validate_ids(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    first = TargetArtifacts(project_dir).read_source().units[0]

    res = client.get(f"/api/projects/test_project/editorial/source?ids={first.id}")
    assert res.status_code == 200
    assert res.json() == {"units": [{"id": first.id, "text": first.text}]}

    res = client.get("/api/projects/test_project/editorial/source?ids=nope_000")
    assert res.status_code == 404

    res = client.get("/api/projects/test_project/editorial/source?ids=,,")
    assert res.status_code == 400


def test_keep_decision_applies_then_changed_evidence_resurfaces(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)

    revision = client.get("/api/projects/test_project/editorial").json()["revision"]
    res = client.post(
        "/api/projects/test_project/editorial/decisions",
        json={
            "expected_revision": revision,
            "issue_ids": ["adapt_issue_001"],
            "disposition": "kept",
        },
    )
    assert res.status_code == 200
    kept = {
        item["issue_id"]: item for item in res.json()["decisions"]
    }["adapt_issue_001"]
    assert kept["disposition"] == "kept"
    assert kept["updated_at"]

    # Recomputed evidence with reworded findings invalidates the old keep: the
    # issue must resurface as open under a new revision.
    adaptation = target.read_adaptation()
    reworded = adaptation.editorial_issues[0].model_copy(
        update={"message": "The aftermath beat is still missing."}
    )
    target.write_adaptation(
        adaptation.model_copy(
            update={"content_sha256": "", "editorial_issues": (reworded,)}
        )
    )
    body = client.get("/api/projects/test_project/editorial").json()
    assert body["revision"] != revision
    resurfaced = {
        item["issue_id"]: item for item in body["decisions"]
    }["adapt_issue_001"]
    assert resurfaced["disposition"] == "open"

    # The stale view can no longer record decisions.
    res = client.post(
        "/api/projects/test_project/editorial/decisions",
        json={
            "expected_revision": revision,
            "issue_ids": ["adapt_issue_001"],
            "disposition": "kept",
        },
    )
    assert res.status_code == 409
    assert res.json()["detail"]["revision"] == body["revision"]


def test_preview_is_persistent_nondestructive_and_truthful(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    before_adaptation = target.adaptation_path.read_bytes()
    before_plan = target.plan_path.read_bytes()

    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={
            "instruction": "Restore the omitted aftermath as captions.",
            "stage": "adapt",
        },
    )
    assert res.status_code == 200
    proposal = res.json()
    assert proposal["stage"] == "adapt"
    assert proposal["status"] == "proposed"
    assert proposal["affected_page_numbers"] == [1]
    assert "explicitly apply" in proposal["impact_summary"]
    assert "unknown until Plan completes" in proposal["impact_summary"]
    assert any("Draw regeneration" in w for w in proposal["estimate_warnings"])
    assert proposal["estimate_credits"] is not None
    assert proposal["estimate_credits"] >= 0

    # Reload retrieves the stored proposal; canonical artifacts are untouched.
    body = client.get("/api/projects/test_project/editorial").json()
    assert [p["id"] for p in body["story_changes"]] == [proposal["id"]]
    assert target.adaptation_path.read_bytes() == before_adaptation
    assert target.plan_path.read_bytes() == before_plan

    # Blank instructions and stale beat references are rejected, not trimmed.
    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "   ", "stage": "plan"},
    )
    assert res.status_code == 400
    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={
            "instruction": "Repace page one.",
            "stage": "plan",
            "adapted_beat_ids": ["beat_9999"],
        },
    )
    assert res.status_code == 409
    assert "revision" in res.json()["detail"]




def test_plan_preview_subset_reports_all_pages_with_focus_retained(
    tmp_path: Path,
):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    before = target.read_plan()
    second = ComicPage(
        revision=1,
        page_number=2,
        adaptation_revision=before.adaptation_revision,
        adaptation_sha256=before.adaptation_sha256,
        emphasis="transition",
        density_intent="standard",
        content=(
            PageContent(
                id="c002",
                order=1,
                beat_ids=("beat_0001",),
                visual_intent="Silence settles over the room.",
            ),
        ),
        reading_order=("c002",),
    )
    target.write_page(second)
    target.write_plan(
        BookPlan(
            revision=before.revision + 1,
            adaptation_revision=before.adaptation_revision,
            adaptation_sha256=before.adaptation_sha256,
            target_page_min=before.target_page_min,
            target_page_max=before.target_page_max,
            pages=(
                *before.pages,
                PlannedPageRevision(
                    page_number=2,
                    revision=second.revision,
                    content_sha256=second.content_sha256,
                ),
            ),
            editorial_issues=before.editorial_issues,
        )
    )

    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={
            "instruction": "Give page two a splash reveal.",
            "stage": "plan",
            "page_numbers": [2],
        },
    )
    assert res.status_code == 200
    proposal = res.json()
    # s5 reruns the entire plan: the subset is focus, not a boundary.
    assert proposal["affected_page_numbers"] == [1, 2]
    assert proposal["page_numbers"] == [2]


def test_apply_guards_unknown_stale_applied_and_busy(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    client = TestClient(app)
    client.event_hooks["request"].append(
        lambda request: request.headers.setdefault("Idempotency-Key", str(uuid4()))
    )
    target = TargetArtifacts(project_dir)
    res = client.post(
        "/api/projects/test_project/story-changes/nope/apply",
        json={"expected_revision": "1"},
    )
    assert res.status_code == 404

    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "plan"},
    ).json()

    res = client.post(
        f"/api/projects/test_project/story-changes/{preview['id']}/apply",
        json={"expected_revision": "0"},
    )
    assert res.status_code == 409

    # A canonical change after preview makes the proposal stale.
    plan = target.read_plan()
    reworded = plan.editorial_issues[0].model_copy(
        update={"message": "Page one still ends without a turn."}
    )
    target.write_plan(
        plan.model_copy(
            update={"content_sha256": "", "editorial_issues": (reworded,)}
        )
    )
    res = client.post(
        f"/api/projects/test_project/story-changes/{preview['id']}/apply",
        json={"expected_revision": preview["revision"]},
    )
    assert res.status_code == 409
    assert "revision" in res.json()["detail"]

    # An applied proposal cannot be applied twice.
    target.write_story_change(
        target.read_story_change(preview["id"]).model_copy(
            update={"status": "applied"}
        )
    )
    res = client.post(
        f"/api/projects/test_project/story-changes/{preview['id']}/apply",
        json={"expected_revision": preview["revision"]},
    )
    assert res.status_code == 409

    # A running stage blocks apply without touching the proposal.
    fresh = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "plan"},
    ).json()
    loop = asyncio.new_event_loop()
    pending = loop.create_future()
    app.state.running_tasks["test-user:test_project"] = pending
    try:
        res = client.post(
            f"/api/projects/test_project/story-changes/{fresh['id']}/apply",
            json={"expected_revision": fresh["revision"]},
        )
    finally:
        app.state.running_tasks.pop("test-user:test_project", None)
        pending.cancel()
        loop.close()
    assert res.status_code == 409
    by_id = {
        item["id"]: item
        for item in client.get("/api/projects/test_project/editorial").json()[
            "story_changes"
        ]
    }
    assert by_id[fresh["id"]]["status"] == "proposed"


def test_apply_starts_owning_stage_with_directive_and_discloses_chain(
    tmp_path: Path,
):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "plan"},
    ).json()

    with (
        patch(
            "novel_to_comic.server.routers.editorial._start_stage",
            new=AsyncMock(return_value={"status": "started", "stage": "plan"}),
        ) as started,
        patch(
            "novel_to_comic.server.routers.editorial.assert_sufficient_credits"
        ),
        patch(
            "novel_to_comic.server.routers.editorial.get_db",
            return_value=MagicMock(),
        ),
    ):
        res = client.post(
            f"/api/projects/test_project/story-changes/{preview['id']}/apply",
            json={"expected_revision": preview["revision"]},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "started"
    assert body["queued_stage"] == "plan"
    assert body["queued_stages"] == ["plan"]
    started.assert_awaited_once()
    args = started.await_args.args
    assert args[2] == "plan" and args[3] is True
    directive = target.peek_story_directive("plan")
    assert directive is not None
    assert directive.proposal_id == preview["id"]
    assert directive.instruction == "Slow the pacing."


def _write_directive(target: TargetArtifacts, preview: dict) -> None:
    target.write_story_directive(
        StoryChangeDirective(
            proposal_id=preview["id"],
            stage=preview["stage"],
            instruction=preview["instruction"],
            created_at=preview["created_at"],
        )
    )


def test_directive_load_validates_before_any_paid_call(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "adapt"},
    ).json()
    assert target.peek_story_directive("adapt") is None
    _write_directive(target, preview)

    loaded = load_story_directive(target, "adapt")
    assert loaded is not None and loaded.proposal_id == preview["id"]
    # Loading never consumes: only a successful stage run clears.
    assert target.peek_story_directive("adapt") is not None

    applied = mark_story_change_applied(target, preview["id"])
    assert applied is not None and applied.status == "applied"
    assert target.read_story_change(preview["id"]).status == "applied"


def test_corrupt_directive_fails_the_stage_run_before_spend(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    target = TargetArtifacts(project_dir)
    target.story_directive_path("adapt").parent.mkdir(parents=True, exist_ok=True)
    target.story_directive_path("adapt").write_text("{not valid json")

    with patch.object(
        s4_adapt, "produce_book_adaptation", new=AsyncMock()
    ) as produce:
        try:
            asyncio.run(
                s4_adapt.run(
                    Config(), project_dir, StageRuntime("adapt", state, project_dir)
                )
            )
        except StoryDirectiveError as exc:
            assert "apply the story change again" in str(exc)
        else:
            raise AssertionError("corrupt directive must fail the stage run")
    produce.assert_not_awaited()


def test_failed_generation_retains_directive_for_explicit_retry(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Restore the aftermath.", "stage": "adapt"},
    ).json()
    _write_directive(target, preview)

    with patch.object(
        s4_adapt,
        "produce_book_adaptation",
        new=AsyncMock(side_effect=RuntimeError("provider blew up")),
    ):
        try:
            asyncio.run(
                s4_adapt.run(
                    Config(), project_dir, StageRuntime("adapt", state, project_dir)
                )
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("failing generation must propagate")
    # No silent drop and no auto-retry: the authorized instruction and the
    # proposed status survive for an explicit re-apply.
    retained = target.peek_story_directive("adapt")
    assert retained is not None and retained.proposal_id == preview["id"]
    assert target.read_story_change(preview["id"]).status == "proposed"


def test_successful_run_clears_directive_and_marks_applied(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Restore the aftermath.", "stage": "adapt"},
    ).json()
    _write_directive(target, preview)

    with patch.object(
        s4_adapt, "produce_book_adaptation", new=AsyncMock(return_value="ok")
    ):
        assert (
            asyncio.run(
                s4_adapt.run(
                    Config(), project_dir, StageRuntime("adapt", state, project_dir)
                )
            )
            == "ok"
        )
    assert target.peek_story_directive("adapt") is None
    assert target.read_story_change(preview["id"]).status == "applied"


def test_plan_run_consumes_directive_persists_plan_without_draw(
    tmp_path: Path,
):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "plan"},
    ).json()
    _write_directive(target, preview)
    before = target.read_plan()
    expected_model = Config().effective_plan_model()
    captured: dict = {}

    async def _persisting_produce(
        adaptation, references, target_range, /, **kwargs
    ):
        captured["model"] = kwargs.get("model")
        captured["story_instruction"] = kwargs.get("story_instruction")
        captured["generate"] = kwargs.get("generate")
        # A NameError on the restored model selection or a dropped
        # instruction must fail here rather than silently regenerating.
        assert kwargs.get("model") == expected_model
        assert kwargs.get("story_instruction") == preview["instruction"]
        assert callable(kwargs.get("generate"))
        nxt = BookPlan(
            revision=before.revision + 1,
            adaptation_revision=before.adaptation_revision,
            adaptation_sha256=before.adaptation_sha256,
            target_page_min=before.target_page_min,
            target_page_max=before.target_page_max,
            pages=before.pages,
            editorial_issues=before.editorial_issues,
        )
        target.write_plan(nxt)
        return nxt

    with (
        patch("novel_to_comic.narrative_review.require_narrative_review"),
        patch.object(s5_plan, "produce_book_plan", side_effect=_persisting_produce),
        patch.object(
            s5_plan, "generate_json", new=AsyncMock(return_value={"ok": True})
        ) as provider,
    ):
        result = asyncio.run(
            s5_plan.run(Config(), project_dir, StageRuntime("plan", state, project_dir))
        )
        # Drive the real generate closure through the mocked provider so the
        # second model use (inside Plan prompts) is pinned, not just the
        # produce kwarg above.
        awaitable = captured["generate"](
            system_prompt="s", user_content="u", parse=lambda raw: raw
        )
        assert asyncio.run(awaitable) == {"ok": True}
    provider.assert_awaited_once()
    assert provider.await_args.kwargs["model"] == expected_model
    assert result.revision == before.revision + 1
    assert target.read_plan().revision == before.revision + 1
    assert target.peek_story_directive("plan") is None
    assert target.read_story_change(preview["id"]).status == "applied"
    assert not target.book_edition_path.exists()




def test_proposal_revision_is_the_preview_time_fingerprint(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)

    revision = client.get("/api/projects/test_project/editorial").json()["revision"]
    proposal = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "plan"},
    ).json()
    # No constant tokens: the proposal carries the exact fingerprint it was
    # compiled against, so both a superseded echo and canonical drift 409.
    assert proposal["revision"] == revision
    assert proposal["revision"].startswith("adapt=1:")


def test_corrupt_editorial_files_fail_explicitly_not_500(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow the pacing.", "stage": "plan"},
    ).json()

    target.story_change_path(preview["id"]).write_text("{not valid json")
    res = client.get("/api/projects/test_project/editorial")
    assert res.status_code == 409
    # FastAPI nests dict details under "detail", matching the repo's 402/409
    # convention: the human message stays a plain string beside file/revision.
    body = res.json()["detail"]
    assert "Canonical story artifacts are unaffected" in body["detail"]
    assert body["file"].startswith("proposal_")
    assert body["revision"].startswith("adapt=1:")
    res = client.post(
        f"/api/projects/test_project/story-changes/{preview['id']}/apply",
        json={"expected_revision": preview["revision"]},
    )
    assert res.status_code == 409

    target.story_change_path(preview["id"]).unlink()
    target.editorial_decisions_path.parent.mkdir(parents=True, exist_ok=True)
    target.editorial_decisions_path.write_text("[broken")
    res = client.get("/api/projects/test_project/editorial")
    assert res.status_code == 409


def test_apply_gates_summed_chain_reservation_not_owning_stage(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    preview = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Restore the aftermath.", "stage": "adapt"},
    ).json()

    reserved_for: list[str] = []

    def _record(config, project_dir, state, stage: str) -> int:
        reserved_for.append(stage)
        return 0

    with (
        patch(
            "novel_to_comic.server.routers.editorial._start_stage",
            new=AsyncMock(return_value={"status": "started", "stage": "adapt"}),
        ),
        patch(
            "novel_to_comic.server.routers.editorial.estimate_stage_credit_reservation",
            side_effect=_record,
        ),
        patch(
            "novel_to_comic.server.routers.editorial.get_db",
            return_value=MagicMock(),
        ),
    ):
        res = client.post(
            f"/api/projects/test_project/story-changes/{preview['id']}/apply",
            json={"expected_revision": preview["revision"]},
        )
    assert res.status_code == 200
    # Adapt auto-chains Plan: the gate must price both, never Draw.
    assert reserved_for == ["adapt", "plan"]
    assert res.json()["queued_stages"] == ["adapt", "plan"]


def test_schema_violations_are_422_not_400(tmp_path: Path):
    project_dir, state = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    revision = client.get("/api/projects/test_project/editorial").json()["revision"]

    # Empty (not merely blank) input and off-contract enums never reach the
    # handlers: FastAPI body validation answers 422.
    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "", "stage": "plan"},
    )
    assert res.status_code == 422
    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "Slow down.", "stage": "draw"},
    )
    assert res.status_code == 422
    res = client.post(
        "/api/projects/test_project/editorial/decisions",
        json={
            "expected_revision": revision,
            "issue_ids": ["adapt_issue_001"],
            "disposition": "maybe",
        },
    )
    assert res.status_code == 422
    # Whitespace-only instructions and unknown immutable references are
    # semantic rejections from the handlers: 400.
    res = client.post(
        "/api/projects/test_project/story-changes/preview",
        json={"instruction": "   ", "stage": "plan"},
    )
    assert res.status_code == 400
