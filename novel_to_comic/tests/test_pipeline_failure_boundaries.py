import asyncio
from functools import wraps
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from novel_to_comic.config import Config
from novel_to_comic.server.credited_job import CreditReservationDenied
from novel_to_comic.server.event_channel import EventChannel
from novel_to_comic.server.routers import pipeline
from novel_to_comic.state import PipelineState, StageState, StageStatus, load_state, save_state
from novel_to_comic.target_artifacts import TargetArtifacts


def run_async(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


def existing_project(tmp_path):
    state = PipelineState(
        project_name="book", novel_path="novel.txt",
        created_at="2026-01-01T00:00:00Z",
    )
    state.stages["extract"] = StageState(status=StageStatus.COMPLETE)
    save_state(state, tmp_path)
    artifact = tmp_path / "story_bible.json"
    artifact.write_text('{"paid": "prior output"}')
    return state, artifact


@run_async
async def test_rejected_rerun_keeps_paid_output_and_state(tmp_path, monkeypatch):
    state, artifact = existing_project(tmp_path)
    before = (tmp_path / "state.json").read_bytes()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(running_tasks={}, style_tasks={}, generation_jobs={})))
    monkeypatch.setattr(pipeline, "estimate_stage_credit_reservation", lambda *args: 100)
    monkeypatch.setattr(pipeline, "get_db", lambda: object())

    def reject(*args, **kwargs):
        raise HTTPException(402, "Insufficient credits")

    monkeypatch.setattr(pipeline, "assert_sufficient_credits", reject)
    with pytest.raises(HTTPException) as denied:
        await pipeline._start_stage(request, "book", "extract", True, (tmp_path, Config(), state), "account")
    assert denied.value.status_code == 402
    assert artifact.read_text() == '{"paid": "prior output"}'
    assert (tmp_path / "state.json").read_bytes() == before


@run_async
async def test_reservation_race_rejection_does_not_reset_rerun(tmp_path, monkeypatch):
    state, artifact = existing_project(tmp_path)
    before = (tmp_path / "state.json").read_bytes()

    async def reject(**kwargs):
        raise CreditReservationDenied("Another action consumed the balance")

    monkeypatch.setattr(pipeline, "run_credited_stage", reject)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)
    await pipeline._run_stage_with_credits("extract", Config(), tmp_path, state, EventChannel(), "account", "book", rerun=True)
    assert artifact.read_text() == '{"paid": "prior output"}'
    assert (tmp_path / "state.json").read_bytes() == before


@pytest.mark.parametrize(("cause", "detail", "credit_blocked", "outcome", "error_type"), [
    (HTTPException(402, {"error": "insufficient_credits", "message": "Insufficient credits"}),
     {"error": "insufficient_credits", "message": "Insufficient credits"}, True, "blocked", "insufficient_credits"),
    (ValueError("estimate defect"), None, False, "failed", "ValueError"),
])
@run_async
async def test_only_a_balance_shortfall_is_reported_as_a_credit_block(
    tmp_path, monkeypatch, cause, detail, credit_blocked, outcome, error_type,
):
    state, _ = existing_project(tmp_path)
    server_events, lifecycle = [], []

    async def reject(**kwargs):
        raise CreditReservationDenied("Blocked", detail) from cause

    monkeypatch.setattr(pipeline, "run_credited_stage", reject)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda name, **kwargs: server_events.append(name))
    monkeypatch.setattr(pipeline, "capture_lifecycle", lambda app, name, attempt_id, **kwargs: lifecycle.append((name, kwargs["properties"])))
    await pipeline._run_stage_with_credits("extract", Config(), tmp_path, state, EventChannel(), "account", "book")

    assert ("credit_blocked" in server_events) is credit_blocked
    failed = [properties for name, properties in lifecycle if name == "stage_failed"]
    assert [(p["outcome"], p["error_type"]) for p in failed] == [(outcome, error_type)]
    assert state.stages["extract"].status == StageStatus.FAILED


def test_failed_stage_reset_returns_pending_without_destroying_outputs(tmp_path):
    state, artifact = existing_project(tmp_path)
    state.stages["extract"] = StageState(status=StageStatus.FAILED, error="provider unavailable")
    save_state(state, tmp_path)
    response = pipeline.reset_stage("extract", "book", (tmp_path, Config(), state), "account")
    assert response == {"status": "reset", "reset": ["extract"]}
    assert load_state(tmp_path).stages["extract"].status == StageStatus.PENDING
    assert artifact.read_text() == '{"paid": "prior output"}'


@run_async
async def test_missing_style_rejects_rerun_without_reset(tmp_path, monkeypatch):
    state, artifact = existing_project(tmp_path)
    state.stages["cast"] = StageState(status=StageStatus.COMPLETE)
    save_state(state, tmp_path)
    before = (tmp_path / "state.json").read_bytes()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(running_tasks={}, style_tasks={}, generation_jobs={})))
    monkeypatch.setattr("novel_to_comic.server.routers.styles.is_style_selected", lambda *args: False)
    with pytest.raises(HTTPException) as denied:
        await pipeline._start_stage(request, "book", "cast", True, (tmp_path, Config(), state), "account")
    assert denied.value.status_code == 403
    assert artifact.exists()
    assert (tmp_path / "state.json").read_bytes() == before


def adaptation_work(tmp_path):
    state, _ = existing_project(tmp_path)
    state.stages["cast"] = StageState(status=StageStatus.COMPLETE)
    state.stages["adapt"] = StageState(status=StageStatus.FAILED, error="narrative_review_padding")
    state.stages["plan"] = StageState(status=StageStatus.COMPLETE)
    save_state(state, tmp_path)
    paths = ["adapt/failed_candidate.json", "plan/book.json", "draw/page.png", "exports/book.pdf",
             ".checkpoints/adapt/responses/old.json", ".checkpoints/adapt/work/budget.json",
             ".checkpoints/plan/work/budget.json"]
    upstream = ["source/source.json", "brief/adaptation_brief.json", "samples/style.png",
                "refs/character.png", "story_changes/directive_adapt.json"]
    for name in paths + upstream:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    return state, paths, upstream


@run_async
@pytest.mark.parametrize("rerun", [False, True])
async def test_adapt_restart_archives_only_after_hold_and_resume_keeps_work(tmp_path, monkeypatch, rerun):
    state, paths, upstream = adaptation_work(tmp_path)
    before = (tmp_path / "state.json").read_bytes()

    async def credited(**kwargs):
        assert kwargs["fresh_adaptation"] is rerun
        assert all((tmp_path / path).exists() for path in paths)
        await kwargs["run"]()
        return "held-job"

    async def run(stage, config, project_dir, active_state, queue, **_kwargs):
        assert stage == "adapt"
        assert all((tmp_path / path).exists() is not rerun for path in paths)
        assert all((tmp_path / path).read_text() == path for path in upstream)
        assert active_state.stages["plan"].status == (StageStatus.PENDING if rerun else StageStatus.COMPLETE)
        # Stop here without invoking providers or auto-chaining.
        active_state.stages[stage].status = StageStatus.FAILED

    monkeypatch.setattr(pipeline, "run_credited_stage", credited)
    monkeypatch.setattr(pipeline, "_run_stage", run)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)
    await pipeline._run_stage_with_credits("adapt", Config(), tmp_path, state, EventChannel(), "account", "book", rerun=rerun)
    archives = list((tmp_path / ".checkpoints/restarts").glob("*"))
    assert len(archives) == int(rerun)
    if rerun:
        assert (archives[0] / "state.json").read_bytes() == before
        assert all((archives[0] / path).read_text() == path for path in paths)


@run_async
async def test_adapt_restart_credit_race_preserves_checkpoints(tmp_path, monkeypatch):
    state, paths, _ = adaptation_work(tmp_path)
    before = (tmp_path / "state.json").read_bytes()

    async def reject(**kwargs):
        raise CreditReservationDenied("Insufficient credits")

    monkeypatch.setattr(pipeline, "run_credited_stage", reject)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)
    await pipeline._run_stage_with_credits("adapt", Config(), tmp_path, state, EventChannel(), "account", "book", rerun=True)
    assert all((tmp_path / path).read_text() == path for path in paths)
    assert (tmp_path / "state.json").read_bytes() == before
    assert not (tmp_path / ".checkpoints/restarts").exists()


def test_adapt_archive_failure_restores_moved_work(tmp_path, monkeypatch):
    from pathlib import Path

    _, paths, upstream = adaptation_work(tmp_path)
    rename = Path.rename

    def fail_midway(path, destination):
        if path == tmp_path / "plan":
            raise OSError("Archive unavailable")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_midway)
    with pytest.raises(OSError, match="Archive unavailable"):
        TargetArtifacts(tmp_path).archive_adaptation_work()
    assert all((tmp_path / path).read_text() == path for path in paths + upstream)
    assert not list((tmp_path / ".checkpoints/restarts").iterdir())


@run_async
async def test_adapt_restart_estimate_ignores_saved_draft_and_old_plan(tmp_path, monkeypatch):
    from novel_to_comic.stages import s4_adapt

    state, _, _ = adaptation_work(tmp_path)
    calls = []

    def fresh_cost(config, project_dir, active_state, *, fresh=False):
        calls.append(fresh)
        return 2.0 if fresh else 0.0

    monkeypatch.setattr(s4_adapt, "estimate_cost", fresh_cost)
    monkeypatch.setattr("novel_to_comic.server.credits.mock_mode_active", lambda config: False)
    monkeypatch.setattr(pipeline.UnifiedCostResolver, "estimate_stage_cost", lambda *args: pytest.fail("Old plan must not enter fresh quote"))
    result = await pipeline.estimate_stage_cost(None, "book", stage="adapt", rerun=True, project=(tmp_path, Config(), state), user_id="account")
    assert calls == [True]
    assert result["estimate_credits"] > 0
    assert result["reserved_credits"] >= result["estimate_credits"]


@pytest.mark.parametrize("case", ["current", "changed_page", "missing_request", "missing_page", "different_request"])
def test_page_job_history_is_bound_to_current_frozen_input(tmp_path, case):
    from .test_complete_page_draw import _compile, _page

    target = TargetArtifacts(tmp_path)
    compiled = _compile(tmp_path)
    if case != "missing_page":
        target.write_page(_page(visual_intent="A newly planned scene.") if case == "changed_page" else _page())
    if case != "missing_request":
        target.write_request(compiled.request, request_revision=1)
    jobs = [{
        "id": "old-or-current-job", "kind": "complete_page_draw", "status": "failed",
        "payload": {"page_number": compiled.request.page_number,
                    "request_sha256": "f" * 64 if case == "different_request" else compiled.request.request_sha256},
    }, {"id": "cast-history", "kind": "character_reference", "status": "failed", "payload": {}}]
    pipeline._mark_current_page_jobs(target, jobs)
    assert jobs[0]["is_current_page"] is (case == "current")
    assert jobs[0]["status"] == "failed"  # History is retained, not deleted or relabeled as successful.
    assert "is_current_page" not in jobs[1]


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
@pytest.mark.parametrize("changed", [False, True])
def test_admitted_page_job_is_current_before_request_artifact_exists(tmp_path, status, changed):
    from .test_complete_page_draw import _compile, _page

    target = TargetArtifacts(tmp_path)
    compiled = _compile(tmp_path)
    target.write_page(_page(visual_intent="A changed scene.") if changed else _page())
    jobs = [{"id": "admitted", "kind": "complete_page_draw", "status": status,
             "payload": {"page_number": compiled.request.page_number,
                         "request_sha256": compiled.request.request_sha256}}]
    pipeline._mark_current_page_jobs(target, jobs, {
        "admitted": compiled.request.model_dump(mode="json"),
    })
    assert jobs[0]["is_current_page"] is (not changed)
    assert not target.request_revisions(compiled.request.page_number)


def test_jobs_endpoint_restores_queued_page_visibility_from_durable_command(tmp_path):
    from .test_complete_page_draw import _compile, _page
    from novel_to_comic.server.generation_jobs import GenerationJob
    from novel_to_comic.server.job_commands import command

    target = TargetArtifacts(tmp_path)
    compiled = _compile(tmp_path)
    target.write_page(_page())
    job = GenerationJob(
        id="waiting", project_name=pipeline.project_key("account", "book"),
        kind="complete_page_draw", label="Page 1", sequence=1, runner=None,
        payload={"page_number": compiled.request.page_number,
                 "request_sha256": compiled.request.request_sha256},
        command=command("page_draw", tmp_path, Config(),
                        request=compiled.request.model_dump(mode="json")),
    )
    app = SimpleNamespace(state=SimpleNamespace(generation_jobs={job.id: job}))
    result = pipeline.get_generation_jobs(
        SimpleNamespace(app=app), "book", ids=None,
        project=(tmp_path, Config(), None), user_id="account",
    )
    assert result["jobs"][0]["status"] == "queued"
    assert result["jobs"][0]["is_current_page"] is True
    assert "command" not in result["jobs"][0]
    assert not target.request_revisions(compiled.request.page_number)


@run_async
@pytest.mark.parametrize("needs_repair", [True, False])
async def test_continuing_plan_repairs_an_adaptation_no_plan_can_satisfy(tmp_path, monkeypatch, needs_repair):
    # Kaitlin Out of Space: a tightened Adapt contract rejected the published
    # script. The user can only Continue Plan, so the server must route that
    # action through Adapt's targeted repair and then chain Plan itself.
    state = PipelineState(project_name="book", novel_path="novel.txt", created_at="2026-01-01T00:00:00Z")
    for name in ("extract", "brief", "style", "cast", "adapt"):
        state.stages[name] = StageState(status=StageStatus.COMPLETE)
    state.stages["plan"] = StageState(status=StageStatus.FAILED, error="compound_appearance_change")
    save_state(state, tmp_path)
    repaired = {"done": False}
    ran = []

    async def credited(**kwargs):
        await kwargs["run"]()
        return "held-job"

    async def run(stage, config, project_dir, active_state, queue, **_kwargs):
        ran.append(stage)
        if stage == "adapt":
            repaired["done"] = True
        active_state.stages[stage].status = StageStatus.COMPLETE

    from novel_to_comic.stages import s4_adapt
    monkeypatch.setattr(s4_adapt, "published_adaptation_needs_repair",
                        lambda project_dir: needs_repair and not repaired["done"])
    monkeypatch.setattr(pipeline, "run_credited_stage", credited)
    monkeypatch.setattr(pipeline, "_run_stage", run)
    monkeypatch.setattr(pipeline, "capture_server_event", lambda *args, **kwargs: None)

    await pipeline._run_stage_with_credits("plan", Config(), tmp_path, state, EventChannel(), "account", "book")

    assert ran == (["adapt", "plan"] if needs_repair else ["plan"])
    assert state.stages["plan"].status == StageStatus.COMPLETE


@run_async
async def test_stage_exception_reaches_error_tracking_with_its_stage(tmp_path, monkeypatch):
    from novel_to_comic.server import telemetry
    state = PipelineState(project_name="book", novel_path="novel.txt", created_at="2026-01-01T00:00:00Z")
    error = KeyError("panel")

    class Broken:
        async def run(self, config, project_dir, ctx):
            raise error

    captured = []
    monkeypatch.setitem(pipeline.REGISTRY, "plan", Broken())
    monkeypatch.setattr(telemetry, "capture_exception", lambda exc, **kwargs: captured.append((exc, kwargs)))
    await pipeline._run_stage("plan", Config(), tmp_path, state, EventChannel(), user_id="account")
    assert state.stages["plan"].status == StageStatus.FAILED
    assert captured == [(error, {"user_id": "account", "stage": "plan"})]


@run_async
async def test_plan_estimate_rejects_a_blank_visual_anchor_with_a_rerun_instruction(tmp_path, monkeypatch):
    from novel_to_comic.artifacts import write_story_bible
    from novel_to_comic.models.story_bible import Character, StoryBible
    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    state, _ = existing_project(tmp_path)
    write_story_bible(tmp_path, StoryBible(
        title="Book", author="Author", total_scenes=0, scenes=[], locations=[], narrative_arcs=[],
        characters=[Character(
            id="char_001", name="Ari", visual_anchor="", age_range="adult", gender="male",
            distinguishing_features=[], default_outfit="coat", first_appearance_scene="scene_001",
        )],
    ))
    monkeypatch.setattr(
        pipeline.UnifiedCostResolver, "estimate_stage_cost",
        lambda config, project_dir, active_state, stage: approved_visual_inventory(project_dir),
    )

    with pytest.raises(HTTPException) as error:
        await pipeline.estimate_stage_cost(None, "book", stage="plan", project=(tmp_path, Config(), state), user_id="account")

    assert error.value.status_code == 409
    assert error.value.detail == (
        "These Story Bible entries have no visual anchor: Ari (char_001). "
        "Add the missing descriptions in the Cast station, or rerun Extract."
    )
