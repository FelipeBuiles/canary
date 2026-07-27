from __future__ import annotations

from pathlib import Path
from starlette.testclient import TestClient

from novel_to_comic.server.app import create_app
from novel_to_comic.server.deps import get_project
from novel_to_comic.state import save_state, PipelineState
from novel_to_comic.artifacts import write_story_bible
from novel_to_comic.models.story_bible import StoryBible
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
