from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

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
from tests.queue_fixtures import create_app
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

    response = _client(tmp_path).post("/api/projects/demo/parts/part_0001/export/preflight")

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

    stale = client.get("/api/projects/demo/parts/part_0001/export/preflight")

    assert stale.status_code == 404

    target.write_preflight(
        preflight.model_copy(
            update={"validator_version": FINISH_PREFLIGHT_VALIDATOR_VERSION}
        )
    )
    current = client.get("/api/projects/demo/parts/part_0001/export/preflight")

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
    assert client.get("/api/projects/demo/parts/part_0001/export/preflight").status_code == 200

    export.write_bytes(b"x" * len(data))
    assert client.get("/api/projects/demo/parts/part_0001/export/preflight").status_code == 404
    assert export.read_bytes() == b"x" * len(data)
    assert target.read_preflight() == preflight
    base = "/api/projects/demo/parts/part_0001/export"
    assert client.get(base + "/pdf").status_code == 404
    # Trigger now attempts a free rebuild; this fixture has no source inputs.
    assert client.post(base + "/?format=pdf").status_code == 422

    export.unlink()
    assert client.get("/api/projects/demo/parts/part_0001/export/preflight").status_code == 404


def test_private_download_uses_a_verified_descriptor_even_after_invalidation(tmp_path: Path, monkeypatch):
    from novel_to_comic.page_finishing import open_verified_package
    client = _client(tmp_path)
    target = TargetArtifacts(tmp_path / "demo")
    from .test_page_finishing import _write_valid_book
    from novel_to_comic.page_finishing import finish_book
    target, _ = _write_valid_book(tmp_path / "demo")
    finish_book(target,formats=("pdf",))
    data = target.export_path("pdf").read_bytes()
    def open_then_invalidate(artifacts, fmt):
        result = open_verified_package(artifacts, fmt)
        artifacts.invalidate_finish()
        return result
    monkeypatch.setattr("novel_to_comic.server.routers.export.open_verified_package", open_then_invalidate)
    monkeypatch.setenv("R2_PUBLIC_URL", "https://public.example.test")
    response = client.get("/api/projects/demo/parts/part_0001/export/pdf", follow_redirects=False)
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["cache-control"] == "private, no-store"
    assert "location" not in response.headers


def test_orphaned_export_is_rejected(tmp_path: Path):
    client = _client(tmp_path)
    path = TargetArtifacts(tmp_path / "demo").export_path("pdf")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"orphan")
    assert client.get("/api/projects/demo/parts/part_0001/export/pdf").status_code == 404


def test_export_lock_uses_full_workspace_identity(tmp_path: Path):
    from novel_to_comic.server.routers.export import _get_export_lock
    client = _client(tmp_path)
    first = _get_export_lock(client.app, str(tmp_path / "alice/book/parts/part_0001"))
    second = _get_export_lock(client.app, str(tmp_path / "bob/book/parts/part_0001"))
    assert first is not second


def test_stale_cached_export_is_rebuilt_in_the_same_request(tmp_path: Path):
    from .test_page_finishing import _write_valid_book
    from novel_to_comic.page_finishing import finish_book

    client = _client(tmp_path)
    target, _ = _write_valid_book(tmp_path / "demo")
    finish_book(target, formats=("pdf",))
    expected_page = target.normalized_page_path(1).read_bytes()
    target.export_path("pdf").write_bytes(b"corrupt")
    response = client.post("/api/projects/demo/parts/part_0001/export/?format=pdf")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"
    download = client.get("/api/projects/demo/parts/part_0001/export/pdf")
    assert download.status_code == 200
    from pypdf import PdfReader
    from PIL import Image
    import io
    assert len(PdfReader(io.BytesIO(download.content)).pages) == 1
    actual_page = target.normalized_page_path(1).read_bytes()
    # Regenerated ICC profiles can have different creation timestamps.
    with Image.open(io.BytesIO(expected_page)) as expected, Image.open(io.BytesIO(actual_page)) as actual:
        assert actual.size == expected.size
        assert actual.mode == expected.mode
        assert actual.tobytes() == expected.tobytes()
    preflight = target.read_preflight()
    assert hashlib.sha256(actual_page).hexdigest() == preflight.pages[0].normalized_image_sha256
    package = preflight.packages[0]
    assert hashlib.sha256(download.content).hexdigest() == package.content_sha256
