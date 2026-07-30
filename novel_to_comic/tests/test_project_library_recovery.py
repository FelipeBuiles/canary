"""Recovery behavior for projects written before the full-page cutover."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.applications import Starlette
from starlette.requests import Request

from novel_to_comic.server.routers.projects import delete_project, list_projects
from novel_to_comic.state import create_initial_state, save_state


def _request() -> Request:
    app = Starlette()
    app.state.generation_jobs = {}
    app.state.running_tasks = {}
    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/projects/",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 0),
            "app": app,
        }
    )


def _db_with_projects(rows: list[dict]) -> MagicMock:
    db = MagicMock()
    query = db.table.return_value.select.return_value.eq.return_value.order.return_value
    query.execute.return_value.data = rows
    return db


def test_library_marks_removed_stage_projects_for_recovery(tmp_path: Path) -> None:
    project_dir = tmp_path / "user-1" / "old-book"
    project_dir.mkdir(parents=True)
    save_state(
        create_initial_state("Old Book", str(project_dir / "input" / "book.txt")),
        project_dir,
    )
    state_path = project_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["stages"]["storyboard"] = {}
    state_path.write_text(json.dumps(state))

    db = _db_with_projects(
        [
            {
                "id": "project-1",
                "name": "old-book",
                "created_at": "2026-06-01T00:00:00+00:00",
            }
        ]
    )

    with patch("novel_to_comic.server.routers.projects.get_db", return_value=db):
        projects = list_projects(
            request=_request(),
            projects_dir=tmp_path,
            user_id="user-1",
        )

    assert projects == [
        {
            "id": "project-1",
            "name": "old-book",
            "project_name": "Old Book",
            "author": None,
            "created_at": "2026-06-01T00:00:00+00:00",
            "total_cost_credits": 0,
            "furthest_stage": None,
            "is_running": False,
            "has_cover": False,
            "page_count": 0,
            "page_issue_summary": None,
            "finish_ready": False,
            "cover_job": None,
            "incompatible": True,
            "incompatibility_reason": "This project was created with an older pipeline version and must be deleted.",
        }
    ]


def test_library_marks_corrupt_state_for_recovery(tmp_path: Path) -> None:
    project_dir = tmp_path / "user-1" / "broken-book"
    project_dir.mkdir(parents=True)
    (project_dir / "state.json").write_text("{not-json")
    db = _db_with_projects(
        [
            {
                "id": "project-2",
                "name": "broken-book",
                "created_at": "2026-06-02T00:00:00+00:00",
            }
        ]
    )

    with patch("novel_to_comic.server.routers.projects.get_db", return_value=db):
        projects = list_projects(
            request=_request(),
            projects_dir=tmp_path,
            user_id="user-1",
        )

    assert projects[0]["project_name"] == "broken-book"
    assert projects[0]["incompatible"] is True


def test_delete_reaches_incompatible_project_without_loading_state(tmp_path: Path) -> None:
    project_dir = tmp_path / "user-1" / "old-book"
    project_dir.mkdir(parents=True)
    (project_dir / "state.json").write_text("{not-json")
    db = MagicMock()

    with patch("novel_to_comic.server.routers.projects.get_db", return_value=db):
        response = delete_project(
            request=_request(),
            project_id="project-1",
            project_dir=project_dir,
            user_id="user-1",
        )

    assert response == {"status": "deleted", "id": "project-1"}
    assert not project_dir.exists()
    db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.assert_called_once()
