from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from starlette.testclient import TestClient
from unittest.mock import MagicMock

from novel_to_comic.server.app import create_app
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.routers import pipeline
from novel_to_comic.server.routers import projects
from novel_to_comic.server.routers import styles
from novel_to_comic.state import save_state, PipelineState, StageState, StageStatus
from novel_to_comic.artifacts import read_story_bible, write_story_bible
from novel_to_comic.briefing import propose_brief
from novel_to_comic.models.story_bible import Scene, StoryBible
from novel_to_comic.models.validation import InvariantFailure, StageValidation
from novel_to_comic.source_extraction import produce_source_document
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.config import Config


def _make_state() -> PipelineState:
    return PipelineState(
        project_name="Test Project",
        novel_path="input/test.txt",
        created_at="2026-01-01T00:00:00Z",
    )


def test_get_story_missing_artifact_returns_404(tmp_path: Path):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    state = _make_state()
    save_state(state, project_dir)

    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    client = TestClient(app)

    # Calling /story when story_bible.json doesn't exist should return 404 Not Found
    res = client.get("/api/projects/test_project/story")
    assert res.status_code == 404
    assert "story_bible" in res.json()["detail"]

    # Calling /story-bible when story_bible.json doesn't exist should return 404 Not Found
    res_bible = client.get("/api/projects/test_project/story-bible")
    assert res_bible.status_code == 404
    assert "story_bible" in res_bible.json()["detail"]


def test_get_story_existing_artifact_returns_200(tmp_path: Path):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    state = _make_state()
    save_state(state, project_dir)
    bible = StoryBible(
        title="Test Title",
        author="Test Author",
        total_scenes=0,
        characters=[],
        locations=[],
        scenes=[],
        narrative_arcs=[],
    )
    write_story_bible(project_dir, bible)

    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    client = TestClient(app)

    res = client.get("/api/projects/test_project/story")
    assert res.status_code == 200
    data = res.json()
    assert data["story_bible"]["title"] == "Test Title"
    assert data["story_bible"]["author"] == "Test Author"
    assert data["brief"] is None


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


def _story_project(tmp_path: Path) -> tuple[Path, PipelineState, StoryBible]:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    state = _make_state()
    save_state(state, project_dir)
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
    produce_source_document(
        TargetArtifacts(project_dir),
        "The door opened. A light burned. Nothing moved.",
        bible,
    )
    return project_dir, state, bible


def _client(
    tmp_path: Path,
    project_dir: Path,
    state: PipelineState,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    client.event_hooks["request"].append(
        lambda request: request.headers.setdefault("Idempotency-Key", str(uuid4()))
    )
    return client


def test_invalid_persisted_adaptation_is_a_concise_conflict(tmp_path: Path):
    project_dir, state, _bible = _story_project(tmp_path)
    adaptation_path = TargetArtifacts(project_dir).adaptation_path
    adaptation_path.parent.mkdir(parents=True)
    adaptation_path.write_text('{"revision": 1, "content_sha256": "' + "a" * 64 + '"}')
    client = _client(
        tmp_path,
        project_dir,
        state,
        raise_server_exceptions=False,
    )

    response = client.get("/api/projects/test_project/adaptation")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Stored book adaptation is incompatible with the current pipeline. "
        "Rerun Adapt to rebuild it."
    )


def _write_draft_brief(project_dir: Path) -> None:
    TargetArtifacts(project_dir).write_brief(
        propose_brief(
            {
                "story_promises": ["The witness never recovers."],
                "themes": ["Knowledge has a cost."],
                "point_of_view": "First person.",
                "narrator_treatment": "Captions carry the testimony.",
                "tone": "Cosmic dread.",
                "essential_events": ["The door opens."],
                "character_turns": ["The witness stops looking."],
                "desired_emphasis": ["Hold the aftermath."],
                "transformation_level": "faithful",
                "target_page_min": 24,
                "target_page_max": 32,
            }
        )
    )


def test_editing_the_story_bible_rederives_the_source_scenes(tmp_path: Path):
    # Source scenes are derived from the bible's anchors. Leaving them behind
    # would let Adapt read scene ranges the edited bible no longer describes.
    project_dir, state, bible = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    target = TargetArtifacts(project_dir)
    assert [scene.id for scene in target.read_source().scenes] == [
        "scene_001",
        "scene_002",
    ]

    edited = bible.model_copy(
        update={
            "total_scenes": 2,
            "scenes": [
                _anchor_scene("scene_001", "The door", "The door opened."),
                _anchor_scene("scene_002", "The light", "A light burned."),
            ],
        }
    )
    response = client.put(
        "/api/projects/test_project/story-bible",
        json=edited.model_dump(mode="json"),
    )

    assert response.status_code == 200
    rebuilt = target.read_source()
    assert [scene.title for scene in rebuilt.scenes] == ["The door", "The light"]
    assert rebuilt.scenes[1].first_unit_id == "source_000002"


def test_an_unresolvable_edited_anchor_is_rejected_before_it_is_persisted(
    tmp_path: Path,
):
    project_dir, state, bible = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    edited = bible.model_copy(
        update={
            "scenes": [
                _anchor_scene("scene_001", "The door", "The door opened."),
                _anchor_scene("scene_002", "Absent", "A voice called out."),
            ]
        }
    )

    response = client.put(
        "/api/projects/test_project/story-bible",
        json=edited.model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert "was not found in source" in response.json()["detail"]
    assert read_story_bible(project_dir).scenes[1].title == "Silence"


def test_stage_validation_is_readable_after_a_blocking_stage(tmp_path: Path):
    project_dir, state, _bible = _story_project(tmp_path)
    client = _client(tmp_path, project_dir, state)
    TargetArtifacts(project_dir).write_validation(
        StageValidation(
            owner_stage="plan",
            attempts=2,
            invariant_failures=[
                InvariantFailure(
                    id="plan_failure_target_page_range",
                    owner_stage="plan",
                    code="target_page_range_conflict",
                    message="Required content cannot fit safely.",
                    evidence=["Recommend a minimum of 44 pages."],
                )
            ],
            recommendations=["Recommend a minimum of 44 pages."],
        )
    )

    response = client.get("/api/projects/test_project/validation/plan")

    assert response.status_code == 200
    assert response.json()["recommendations"] == ["Recommend a minimum of 44 pages."]
    assert client.get("/api/projects/test_project/validation/draw").status_code == 404


def test_cast_approval_does_not_start_adapt_with_a_draft_brief(
    tmp_path: Path,
    monkeypatch,
):
    project_dir, state, _bible = _story_project(tmp_path)
    _write_draft_brief(project_dir)
    state.stages["cast"].status = StageStatus.AWAITING_REVIEW
    started: list[str] = []

    async def record_started_stage(stage, *_args, **_kwargs):
        started.append(stage)

    monkeypatch.setattr(pipeline, "_run_stage_with_credits", record_started_stage)
    client = _client(tmp_path, project_dir, state)

    response = client.post("/api/projects/test_project/approve/cast")

    assert response.status_code == 409
    assert response.json()["detail"] == "Adapt requires an approved adaptation brief"
    assert state.stages["cast"].status == StageStatus.AWAITING_REVIEW
    assert started == []


def test_run_adapt_rejects_a_draft_brief_before_enqueuing(
    tmp_path: Path,
    monkeypatch,
):
    project_dir, state, _bible = _story_project(tmp_path)
    _write_draft_brief(project_dir)
    state.stages["cast"].status = StageStatus.COMPLETE
    started: list[str] = []

    async def record_started_stage(stage, *_args, **_kwargs):
        started.append(stage)

    monkeypatch.setattr(pipeline, "_run_stage_with_credits", record_started_stage)
    monkeypatch.setattr(styles, "is_style_selected", lambda *_args: True)
    monkeypatch.setattr(
        pipeline,
        "estimate_stage_credit_reservation",
        lambda *_args: 0,
    )
    monkeypatch.setattr(pipeline, "get_db", lambda: object())
    monkeypatch.setattr(
        pipeline, "assert_sufficient_credits", lambda *_args, **_kwargs: None
    )
    client = _client(tmp_path, project_dir, state)

    response = client.post("/api/projects/test_project/run?stage=adapt")

    assert response.status_code == 409
    assert response.json()["detail"] == "Adapt requires an approved adaptation brief"
    assert state.stages["adapt"].status == StageStatus.PENDING
    assert started == []


def test_status_reopens_story_review_when_draft_brief_has_stale_adapt_failure(
    tmp_path: Path,
    monkeypatch,
):
    project_dir, state, _bible = _story_project(tmp_path)
    _write_draft_brief(project_dir)
    state.stages["brief"] = StageState(
        status=StageStatus.AWAITING_REVIEW,
    )
    state.stages["style"] = StageState(status=StageStatus.COMPLETE)
    state.stages["cast"] = StageState(status=StageStatus.COMPLETE)
    state.stages["adapt"] = StageState(
        status=StageStatus.FAILED,
        error="Adapt requires an approved adaptation brief",
    )
    save_state(state, project_dir)

    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    monkeypatch.setattr(projects, "get_db", lambda: db)
    client = _client(tmp_path, project_dir, state)

    response = client.get("/api/projects/test_project/status")

    assert response.status_code == 200
    assert response.json()["stages"]["brief"]["status"] == "awaiting_review"
    assert response.json()["stages"]["brief"]["approved"] is None
    assert response.json()["stages"]["style"]["status"] == "complete"
    assert response.json()["stages"]["cast"]["status"] == "complete"
    assert response.json()["stages"]["adapt"]["status"] == "pending"


def test_start_draw_can_request_queueing_every_page(
    tmp_path: Path,
    monkeypatch,
):
    project_dir, state, _bible = _story_project(tmp_path)
    state.stages["plan"] = StageState(status=StageStatus.COMPLETE)
    calls: list[dict] = []

    async def record_started_stage(*_args, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(pipeline, "_run_stage_with_credits", record_started_stage)
    monkeypatch.setattr(styles, "is_style_selected", lambda *_args: True)
    client = _client(tmp_path, project_dir, state)

    response = client.post(
        "/api/projects/test_project/run?stage=draw&queue_pages=1"
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["queue_draw_pages"] is True
    assert calls[0]["request"] is not None


def test_brief_reapproval_resumes_adapt_when_cast_is_already_complete(
    tmp_path: Path,
    monkeypatch,
):
    project_dir, state, _bible = _story_project(tmp_path)
    _write_draft_brief(project_dir)
    state.stages["brief"] = StageState(status=StageStatus.AWAITING_REVIEW)
    state.stages["style"] = StageState(status=StageStatus.COMPLETE)
    state.stages["cast"] = StageState(status=StageStatus.COMPLETE)
    started: list[str] = []

    async def record_started_stage(stage, *_args, **_kwargs):
        started.append(stage)

    monkeypatch.setattr(pipeline, "_run_stage_with_credits", record_started_stage)
    client = _client(tmp_path, project_dir, state)

    response = client.post("/api/projects/test_project/approve/brief")

    assert response.status_code == 200
    assert response.json()["auto_started"] == "adapt"
    assert state.stages["brief"].status == StageStatus.COMPLETE
    assert TargetArtifacts(project_dir).read_brief().status == "approved"
    assert started == ["adapt"]


def test_brief_stage_repairs_an_invalid_inference_with_one_retry(
    tmp_path: Path,
    caplog,
):
    """Anything normalization cannot fix gets the errors fed back, once."""

    import asyncio

    from novel_to_comic.clients import structured_call
    from novel_to_comic.stages import s2_brief
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.usage import ApiResult, UsageRecord

    project_dir, state, bible = _story_project(tmp_path)
    complete = {
        "story_promises": ["The witness never recovers."],
        "themes": ["Knowledge has a cost."],
        "point_of_view": "First person.",
        "narrator_treatment": "Captions carry the testimony.",
        "tone": "Cosmic dread.",
        "essential_events": ["The door opens."],
        "character_turns": ["The witness stops looking."],
        "desired_emphasis": "Hold the aftermath.",
        "transformation_level": "Faithful, adapted to comics.",
        "target_page_min": 24,
        "target_page_max": 32,
    }
    # Structured model output sometimes expands each character turn into an
    # object even though the persisted contract requires plain strings.
    responses = [
        {
            **complete,
            "character_turns": [
                {"character": "Witness", "turn": "He stops looking."},
                {"character": "Friend", "turn": "She believes him."},
                {"character": "Inspector", "turn": "He closes the case."},
            ],
        },
        complete,
    ]
    prompts: list[str] = []

    async def fake_generate_json(**kwargs):
        prompts.append(kwargs["user_content"])
        return ApiResult(
            value=responses[len(prompts) - 1],
            usage=UsageRecord(
                provider="test",
                model="extract-balanced",
                operation="text",
                input_tokens=100,
                output_tokens=50,
            ),
        )

    original = structured_call.generate_json
    structured_call.generate_json = fake_generate_json
    try:
        brief = asyncio.run(
            s2_brief.run(
                Config(),
                project_dir,
                StageRuntime("brief", state, project_dir),
            )
        )
    finally:
        structured_call.generate_json = original

    assert len(prompts) == 2
    assert "VALIDATION ERRORS" in prompts[1]
    assert "character_turns" in prompts[1]
    assert brief.status == "draft"
    assert brief.transformation_level == "faithful"
    assert brief.desired_emphasis == ("Hold the aftermath.",)
    assert TargetArtifacts(project_dir).read_brief() == brief
    assert len(state.stages["brief"].usage_log) == 2
    warning = next(
        record.message
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.message.startswith("Adaptation brief inference")
    )
    assert warning == (
        "Adaptation brief inference attempt 1/3 rejected; retrying: "
        "character_turns[0, 1, 2]: Input should be a valid string"
    )
    assert "pydantic.dev" not in warning
