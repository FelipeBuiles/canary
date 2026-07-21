import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.assembly.lettering_preflight import LetteringPreflightIssue
from novel_to_comic.assembly.lettering_style import lettering_style_path
from novel_to_comic.config import Config
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.routers import export
from novel_to_comic.server.routers.export import _export_is_fresh
from novel_to_comic.stages.s8_compose import _enforce_lettering_preflight


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


def test_export_anyway_bypasses_render_preflight_for_uncached_export(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(export.limiter, "enabled", False)
    async def fake_preflight(_project_dir):
        return [
            LetteringPreflightIssue(
                code="lettering_obscures_art",
                severity="error",
                page_number=16,
                panel_id="scene_016-005",
                panel_number=5,
                bubble_ids=(),
                message="Panel 5 lettering covers 43% of the art area (maximum 40%).",
            )
        ]

    async def fake_compose_run(
        _config,
        project_dir,
        _ctx,
        *,
        formats,
        rebuild,
        allow_lettering_issues=False,
    ):
        assert formats == ["pdf"]
        assert rebuild is False
        if not allow_lettering_issues:
            raise ValueError("Lettering preflight blocked export")
        export_path = project_dir / "exports" / "comic.pdf"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(b"pdf")

    monkeypatch.setattr(export, "inspect_project_lettering", fake_preflight)
    monkeypatch.setattr(export.s8_compose, "run", fake_compose_run)
    monkeypatch.setattr(export, "r2_configured", lambda: False)
    monkeypatch.setattr(export, "capture_server_event", lambda *args, **kwargs: None)

    app = FastAPI()
    app.include_router(export.router, prefix="/api/projects/{project_id}/export")
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user_001"
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/projects/demo/export/",
        params={"format": "pdf", "allow_issues": "true"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_renderer_startup_failure_returns_actionable_service_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(export.limiter, "enabled", False)
    async def fake_preflight(_project_dir):
        raise RuntimeError(
            "BrowserType.launch: error while loading shared libraries: "
            "libasound.so.2: cannot open shared object file"
        )

    monkeypatch.setattr(export, "inspect_project_lettering", fake_preflight)

    app = FastAPI()
    app.include_router(export.router, prefix="/api/projects/{project_id}/export")
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user_001"
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/projects/demo/export/", params={"format": "pdf"})

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == (
        "The export renderer is temporarily unavailable. Please try again shortly."
    )


def test_compose_renderer_honors_explicit_lettering_override() -> None:
    issues = [
        LetteringPreflightIssue(
            code="lettering_stack_too_tall",
            severity="error",
            page_number=10,
            panel_id="scene_010-004",
            panel_number=4,
            bubble_ids=(),
            message="Panel 4 automatic lettering stack uses 40.4% of the panel height.",
        )
    ]

    with pytest.raises(ValueError, match="page 10, panel 4"):
        _enforce_lettering_preflight(issues, allow_lettering_issues=False)

    _enforce_lettering_preflight(issues, allow_lettering_issues=True)
