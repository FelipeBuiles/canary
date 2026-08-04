"""Contracts for serving project assets to the web app.

The full-page rewrite replaced the page router and dropped its generic asset
reader with the panel-era code that surrounded it. Nothing failed loudly: the
API kept reporting ``has_sample: true`` while every image request 404'd, and
asset 404s are deliberately suppressed from the request log as
not-yet-generated noise. These tests pin the route down so the next rewrite
cannot take it with it.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.testclient import TestClient

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.page import (
    BookPlan,
    ComicPage,
    PageContent,
    PlannedPageRevision,
)
from novel_to_comic.server.app import create_app
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.routers.files import serve_project_file
from novel_to_comic.state import PipelineState, save_state
from novel_to_comic.target_artifacts import TargetArtifacts


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
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
    return TestClient(app), project_dir


def test_every_asset_url_the_ui_builds_is_routable(tmp_path: Path):
    # One per URL shape the web app constructs: style proofs, cast references,
    # plates, props, the cover, generation sidecars, and finish preflight.
    client, project_dir = _client(tmp_path)
    relative_paths = (
        "samples/style_1.png",
        "samples/style_1.png.meta.json",
        "samples/style_1.png.failure.json",
        "samples/validations/style_abc.png",
        "refs/character_ann/sheet.png",
        "refs/character_ann/neutral.png",
        "refs/character_ann/states/state_hurt/portrait.png",
        "refs/props/prop_key/ref.png",
        "plates/location_hall.png",
        "cover/cover.png",
        "finish/preflight.json",
    )
    for relative in relative_paths:
        path = project_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())

    for relative in relative_paths:
        response = client.get(f"/api/projects/demo/files/{relative}")
        assert response.status_code == 200, relative
        assert response.content == relative.encode()
        assert response.headers["cache-control"] == "private, max-age=60"


def test_a_style_proof_is_served_where_the_styles_route_promises_it(tmp_path: Path):
    # get_styles reports has_sample from this exact path, so the two must agree.
    client, project_dir = _client(tmp_path)
    sample = artifacts.style_sample_path(project_dir, 3)
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"\x89PNG\r\n\x1a\n")

    response = client.get("/api/projects/demo/files/samples/style_3.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG\r\n\x1a\n"


def test_a_missing_asset_is_not_found_rather_than_an_error(tmp_path: Path):
    client, _project_dir = _client(tmp_path)
    response = client.get("/api/projects/demo/files/samples/style_9.png")
    assert response.status_code == 404


def test_assets_cannot_escape_the_project_directory(tmp_path: Path):
    # The URL layer normalizes away `..` before routing, so the guard is tested
    # against the handler directly: it is what protects a caller that reaches
    # the function with a traversing relative path (encoded input, or a future
    # in-process caller).
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (tmp_path / "secret.txt").write_text("other tenant")
    sibling = tmp_path / "demo-private"
    sibling.mkdir()
    (sibling / "leak.txt").write_text("sibling project")
    project = (project_dir, Config(), None)

    for escape in (
        "../secret.txt",
        "../demo-private/leak.txt",
        "samples/../../secret.txt",
    ):
        with pytest.raises(HTTPException) as exc_info:
            serve_project_file(escape, project=project)
        assert exc_info.value.status_code == 403, escape


def test_url_encoded_traversal_never_leaks_a_neighbouring_project(tmp_path: Path):
    client, _project_dir = _client(tmp_path)
    sibling = tmp_path / "demo-private"
    sibling.mkdir()
    (sibling / "leak.txt").write_text("sibling project")

    for escape in ("%2e%2e/demo-private/leak.txt", "..%2fdemo-private%2fleak.txt"):
        response = client.get(f"/api/projects/demo/files/{escape}")
        assert response.status_code in (403, 404), escape
        assert b"sibling project" not in response.content, escape


def test_project_credentials_are_not_reachable_as_assets(tmp_path: Path):
    client, project_dir = _client(tmp_path)
    (project_dir / "config.yaml").write_text("litellm_api_key: sk-real-key\n")
    (project_dir / ".env").write_text("LITELLM_API_KEY=sk-real-key\n")

    for secret in ("config.yaml", ".env"):
        response = client.get(f"/api/projects/demo/files/{secret}")
        assert response.status_code == 403, secret


def test_a_page_render_is_cacheable_forever(tmp_path: Path):
    # The book reader pages through a whole book off the bytes the Panels grid
    # already fetched. That only holds if a render revision — which is
    # immutable, corrections write a new revision — is cached without
    # revalidation. Private: renders belong to one user's project.
    client, project_dir = _client(tmp_path)
    render = TargetArtifacts(project_dir).render_path(1, 1)
    render.parent.mkdir(parents=True)
    render.write_bytes(b"page-one-render")

    response = client.get("/api/projects/demo/pages/1/renders/1")

    assert response.status_code == 200
    assert response.content == b"page-one-render"
    assert response.headers["cache-control"] == (
        "private, max-age=31536000, immutable"
    )


def test_a_page_render_preview_is_a_small_immutable_webp(tmp_path: Path):
    client, project_dir = _client(tmp_path)
    render = TargetArtifacts(project_dir).render_path(1, 1)
    render.parent.mkdir(parents=True)
    source = io.BytesIO()
    Image.new("RGB", (1696, 2528), "navy").save(source, "PNG")
    render.write_bytes(source.getvalue())

    response = client.get("/api/projects/demo/pages/1/renders/1/preview/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == (
        "private, max-age=31536000, immutable"
    )
    with Image.open(io.BytesIO(response.content)) as preview:
        assert preview.format == "WEBP"
        assert preview.size == (424, 632)
    assert TargetArtifacts(project_dir).render_preview_path(1, 1, "thumbnail").exists()


def test_named_project_routes_are_not_shadowed_by_the_asset_reader(tmp_path: Path):
    # The asset route is greedy; registering it before a named route would make
    # that route unreachable. `pages` has no artifacts here, so a 404 from the
    # pages handler (not the file reader) is the signal we want.
    client, _project_dir = _client(tmp_path)
    response = client.get("/api/projects/demo/pages")
    assert response.json()["detail"] != "File not found"


def test_pages_route_reads_page_saved_before_panel_roles_were_authored(
    tmp_path: Path,
):
    client, project_dir = _client(tmp_path)
    page = ComicPage(
        revision=1,
        page_number=1,
        adaptation_revision=1,
        adaptation_sha256="a" * 64,
        emphasis="initial",
        density_intent="standard",
        content=[
            PageContent(
                id="item_0001",
                order=1,
                beat_ids=["beat_0001"],
                visual_intent="A scholar opens the forbidden manuscript.",
            )
        ],
        reading_order=["item_0001"],
    )
    stored_page = page.model_dump(mode="json")
    stored_page["content"][0].pop("panel_role")
    stored_page.pop("content_sha256")
    stored_hash = hashlib.sha256(
        json.dumps(
            stored_page,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    stored_page["content_sha256"] = stored_hash
    page_path = TargetArtifacts(project_dir).page_path(1)
    page_path.parent.mkdir(parents=True)
    page_path.write_text(json.dumps(stored_page))
    TargetArtifacts(project_dir).write_plan(
        BookPlan(
            revision=1,
            adaptation_revision=1,
            adaptation_sha256="a" * 64,
            target_page_min=1,
            target_page_max=1,
            pages=[
                PlannedPageRevision(
                    page_number=1,
                    revision=1,
                    content_sha256=stored_hash,
                )
            ],
        )
    )

    response = client.get("/api/projects/demo/pages")

    assert response.status_code == 200
    returned = response.json()["pages"][0]["page"]
    assert returned["content_sha256"] == stored_hash
    assert returned["content"][0]["panel_role"] == "standard"
