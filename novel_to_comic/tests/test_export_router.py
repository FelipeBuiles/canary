from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from novel_to_comic.config import Config
from novel_to_comic.models.finish import (
    FINISH_PREFLIGHT_VALIDATOR_VERSION,
    ExportPackage,
    FinishPreflight,
    FinishProductionSpec,
    FinishResult,
    PreflightPage,
)
from novel_to_comic.server.app import create_app
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.stages import REGISTRY
from novel_to_comic.state import PipelineState, save_state
from novel_to_comic.target_artifacts import TargetArtifacts


def _client(tmp_path: Path) -> TestClient:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    state = PipelineState(
        project_name="Demo",
        novel_path="input/demo.txt",
        created_at="2026-01-01T00:00:00Z",
    )
    save_state(state, project_dir)
    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, Config(), state)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    return TestClient(app)


def test_preflight_endpoint_runs_finish_without_packaging(tmp_path: Path, monkeypatch):
    preflight = FinishPreflight(
        edition_revision=1,
        edition_sha256="a" * 64,
        production=FinishProductionSpec(canvas_width=100, canvas_height=160),
        pages=(
            PreflightPage(
                page_number=1,
                comic_page_revision=1,
                comic_page_sha256="b" * 64,
                render_revision=1,
                render_image_sha256="c" * 64,
            ),
        ),
    )
    run = AsyncMock(return_value=FinishResult(preflight=preflight))
    monkeypatch.setattr(REGISTRY["finish"], "run", run)

    response = _client(tmp_path).post("/api/projects/demo/export/preflight")

    assert response.status_code == 200
    assert response.json()["preflight"]["packages"] == []
    run.assert_awaited_once()
    assert run.await_args.kwargs["formats"] == ()
    assert run.await_args.kwargs["clear_derived_outputs"] is False


def test_get_preflight_reuses_only_the_current_validator_version(tmp_path: Path):
    preflight = FinishPreflight(
        edition_revision=1,
        edition_sha256="a" * 64,
        validator_version=1,
        production=FinishProductionSpec(canvas_width=100, canvas_height=160),
        pages=(
            PreflightPage(
                page_number=1,
                comic_page_revision=1,
                comic_page_sha256="b" * 64,
                render_revision=1,
                render_image_sha256="c" * 64,
            ),
        ),
    )
    client = _client(tmp_path)
    target = TargetArtifacts(tmp_path / "demo")
    target.write_preflight(preflight)

    stale = client.get("/api/projects/demo/export/preflight")

    assert stale.status_code == 404

    target.write_preflight(
        preflight.model_copy(
            update={"validator_version": FINISH_PREFLIGHT_VALIDATOR_VERSION}
        )
    )
    current = client.get("/api/projects/demo/export/preflight")

    assert current.status_code == 200
    assert current.json()["validator_version"] == FINISH_PREFLIGHT_VALIDATOR_VERSION


def test_preflight_requires_available_matching_packages_without_removing_them(tmp_path: Path):
    client = _client(tmp_path)
    target = TargetArtifacts(tmp_path / "demo")
    export = target.export_path("pdf")
    export.parent.mkdir(parents=True)
    data = b"current PDF bytes"
    export.write_bytes(data)
    preflight = FinishPreflight(
        edition_revision=1,
        edition_sha256="a" * 64,
        validator_version=FINISH_PREFLIGHT_VALIDATOR_VERSION,
        production=FinishProductionSpec(canvas_width=100, canvas_height=160),
        pages=(PreflightPage(
            page_number=1, comic_page_revision=1, comic_page_sha256="b" * 64,
            render_revision=1, render_image_sha256="c" * 64,
        ),),
        packages=(ExportPackage(
            format="pdf", relative_path="exports/comic.pdf",
            content_sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data), page_numbers=(1,),
        ),),
    )
    target.write_preflight(preflight)
    assert client.get("/api/projects/demo/export/preflight").status_code == 200

    export.write_bytes(b"x" * len(data))
    assert client.get("/api/projects/demo/export/preflight").status_code == 404
    assert export.read_bytes() == b"x" * len(data)
    assert target.read_preflight() == preflight

    export.unlink()
    assert client.get("/api/projects/demo/export/preflight").status_code == 404


def test_export_download_uploads_the_current_bytes_to_r2_when_configured(
    tmp_path: Path,
    monkeypatch,
):
    client = _client(tmp_path)
    target = TargetArtifacts(tmp_path / "demo")
    export = target.export_path("pdf")
    export.parent.mkdir(parents=True)
    export.write_bytes(b"finalized PDF")
    upload = MagicMock(return_value="https://media.scenewright.ink/export.pdf")
    monkeypatch.setattr(
        "novel_to_comic.server.routers.export.r2_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "novel_to_comic.server.routers.export.upload_export",
        upload,
    )

    response = client.get("/api/projects/demo/export/pdf", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://media.scenewright.ink/export.pdf"
    upload.assert_called_once_with("test-user", "demo", "comic.pdf", b"finalized PDF")
