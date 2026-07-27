from __future__ import annotations

from pathlib import Path
from starlette.testclient import TestClient

from novel_to_comic.server.app import create_app
from novel_to_comic.server.deps import get_project
from novel_to_comic.state import save_state, PipelineState
from novel_to_comic.artifacts import read_story_bible, write_story_bible
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


def _client(tmp_path: Path, project_dir: Path, state: PipelineState) -> TestClient:
    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    return TestClient(app)


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
