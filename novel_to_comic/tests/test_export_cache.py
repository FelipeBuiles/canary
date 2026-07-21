import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.assembly.lettering_preflight import LetteringPreflightIssue
from novel_to_comic.assembly.lettering_style import lettering_style_path
from novel_to_comic.config import Config
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.routers import export
from novel_to_comic.server.routers.export import _export_is_fresh


def _touch(path: Path, timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    os.utime(path, (timestamp, timestamp))


def test_export_cache_is_stale_when_lettering_style_is_newer(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "comic.pdf"
    _touch(tmp_path / "compose" / "pages" / "page_001.json", 100)
    _touch(export_path, 200)
    _touch(lettering_style_path(tmp_path), 300)

    assert _export_is_fresh(tmp_path, export_path) is False


def test_export_cache_is_fresh_when_lettering_style_is_older(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "comic.pdf"
    _touch(tmp_path / "compose" / "pages" / "page_001.json", 100)
    _touch(lettering_style_path(tmp_path), 150)
    _touch(export_path, 200)

    assert _export_is_fresh(tmp_path, export_path) is True


def test_export_anyway_bypasses_blocking_preflight(tmp_path: Path, monkeypatch) -> None:
    export_path = tmp_path / "exports" / "comic.pdf"
    _touch(tmp_path / "compose" / "pages" / "page_001.json", 100)
    _touch(export_path, 200)

    async def fake_preflight(_project_dir):
        return [
            LetteringPreflightIssue(
                code="lettering_stack_too_tall",
                severity="error",
                page_number=13,
                panel_id="scene_013-001",
                panel_number=1,
                bubble_ids=(),
                message="Panel 1 automatic lettering stack is too tall.",
            )
        ]

    monkeypatch.setattr(export, "inspect_project_lettering", fake_preflight)
    monkeypatch.setattr(export, "r2_configured", lambda: False)
    monkeypatch.setattr(export, "capture_server_event", lambda *args, **kwargs: None)

    app = FastAPI()
    app.include_router(export.router, prefix="/api/projects/{project_id}/export")
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user_001"
    client = TestClient(app)

    blocked = client.post(
        "/api/projects/demo/export/",
        params={"format": "pdf"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["message"] == (
        "Export is blocked by 1 lettering issue at page 13, panel 1. "
        "Review them or choose Export Anyway."
    )

    response = client.post(
        "/api/projects/demo/export/",
        params={"format": "pdf", "allow_issues": "true"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "exists"
