"""Display-name edits retain project identity and respect state-writer admission."""
import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from novel_to_comic.config import Config
from novel_to_comic.server import deps
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.routers import projects
from novel_to_comic.state import StageStatus, create_initial_state, load_state, save_state
from tests.test_server_admission import app_at, run_async


@pytest.fixture
def project_app(tmp_path, monkeypatch):
    project_dir = tmp_path / "account" / "original-slug"
    project_dir.mkdir(parents=True)
    state = create_initial_state("Original title", str(project_dir / "input/book.txt"))
    state.stages["extract"].status = StageStatus.COMPLETE
    state.stages["extract"].cost_usd = 0.25
    state.total_cost_usd = 0.5
    state.misc_cost_usd = 0.25
    state.style_template_hash = "pinned-style-hash"
    save_state(state, project_dir)
    row = {
        "id": "project-uuid",
        "user_id": "account",
        "name": "original-slug",
        "created_at": state.created_at.isoformat(),
        "share_token": "stable-share-token",
        "is_public": True,
    }
    db = MagicMock()

    def table(_name):
        query = MagicMock()
        filters = {}
        updates = {}
        query.select.return_value = query
        query.order.return_value = query

        def eq(key, value):
            filters[key] = value
            return query

        def update(values):
            updates.update(values)
            return query

        def execute():
            if not all(row.get(key) == value for key, value in filters.items()):
                return SimpleNamespace(data=[])
            row.update(updates)
            return SimpleNamespace(data=[row.copy()])

        query.eq.side_effect = eq
        query.update.side_effect = update
        query.execute.side_effect = execute
        return query

    db.table.side_effect = table
    monkeypatch.setattr(deps, "get_db", lambda: db)
    monkeypatch.setattr(projects, "get_db", lambda: db)
    monkeypatch.setattr(deps, "load_config", lambda _path: (Config(), None))
    monkeypatch.setattr(deps, "account_config", lambda config, *_args: config)
    app = app_at(tmp_path)
    app.state.projects_dir = tmp_path
    app.include_router(projects.router, prefix="/api/projects")
    return app, project_dir, row


@run_async
async def test_rename_persists_display_name_without_changing_identity_or_artifacts(project_app):
    app, project_dir, row = project_app
    retained = {
        "input/book.txt": b"Original manuscript",
        "story_bible.json": b'{"title":"Source title","author":"Author"}',
        "cover/cover.png": b"existing cover",
        "exports/comic.pdf": b"existing export",
        "pages/page_001/lettering.json": b'{"content_sha256":"unchanged"}',
    }
    for relative_path, content in retained.items():
        path = project_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = load_state(project_dir).model_dump()
    original_row = row.copy()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch("/api/projects/project-uuid", json={"name": " \tRenamed project\n "})
        listing = await client.get("/api/projects/")
        status = await client.get("/api/projects/project-uuid/status")
    assert response.status_code == 200
    assert response.json() == {"id": "project-uuid", "project_name": "Renamed project"}
    assert listing.status_code == 200
    assert listing.json()[0]["project_name"] == "Renamed project"
    assert listing.json()[0]["name"] == "original-slug"
    assert listing.json()[0]["id"] == "project-uuid"
    assert status.status_code == 200
    assert status.json()["project_name"] == "Renamed project"
    assert status.json()["share_token"] == "stable-share-token"
    assert load_state(project_dir).model_dump() == {**before, "project_name": "Renamed project"}
    assert row == original_row
    for relative_path, content in retained.items():
        assert (project_dir / relative_path).read_bytes() == content


@pytest.mark.parametrize("payload", [{"name": " \t\n\u2003 "}, {"name": "x" * 201}, {"name": None}, {"name": 42}, {}])
@run_async
async def test_rename_rejects_invalid_names_without_writing_state(project_app, payload):
    app, project_dir, _row = project_app
    before = (project_dir / "state.json").read_bytes()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch("/api/projects/project-uuid", json=payload)
    assert response.status_code == 422
    assert (project_dir / "state.json").read_bytes() == before


@run_async
async def test_rename_validates_length_after_trimming(project_app):
    app, project_dir, _row = project_app
    name = "é" * 200
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch("/api/projects/project-uuid", json={"name": f"  {name}\n"})
    assert response.status_code == 200
    assert response.json()["project_name"] == name
    assert load_state(project_dir).project_name == name


@run_async
async def test_rename_requires_the_existing_owner_dependency(project_app):
    app, project_dir, _row = project_app
    before = (project_dir / "state.json").read_bytes()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.patch("/api/projects/missing-uuid", json={"name": "New title"})
        app.dependency_overrides[get_current_user] = lambda: "other-account"
        other_owner = await client.patch("/api/projects/project-uuid", json={"name": "New title"})
        app.dependency_overrides.pop(get_current_user)
        anonymous = await client.patch("/api/projects/project-uuid", json={"name": "New title"})
    assert missing.status_code == 404
    assert other_owner.status_code == 404
    assert anonymous.status_code == 401
    assert (project_dir / "state.json").read_bytes() == before


@pytest.mark.parametrize("busy_kind", ["running_tasks", "style_tasks", "queued", "running"])
@run_async
async def test_rename_waits_until_stale_background_writer_finishes(project_app, busy_kind):
    app, project_dir, _row = project_app
    stale = load_state(project_dir)
    guard = None
    if busy_kind in {"running_tasks", "style_tasks"}:
        guard = asyncio.get_running_loop().create_future()
        getattr(app.state, busy_kind)["account:project-uuid"] = guard
    else:
        app.state.generation_jobs["job"] = SimpleNamespace(
            project_name="account:project-uuid", status=busy_kind, kind="project_cover"
        )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rejected = await client.patch("/api/projects/project-uuid", json={"name": "New title"})
        assert rejected.status_code == 409
        assert load_state(project_dir).project_name == "Original title"
        stale.stages["draw"].items_done = 3
        save_state(stale, project_dir)
        if guard is not None:
            guard.set_result(None)
        else:
            app.state.generation_jobs["job"].status = "complete"
        accepted = await client.patch("/api/projects/project-uuid", json={"name": "New title"})
    assert accepted.status_code == 200
    persisted = load_state(project_dir)
    assert persisted.project_name == "New title"
    assert persisted.stages["draw"].items_done == 3


@run_async
async def test_rename_serializes_with_status_reconciliation_before_state_load(project_app, monkeypatch):
    app, project_dir, _row = project_app
    entered, release = Event(), Event()

    def reconcile(_project_dir, state):
        entered.set()
        assert release.wait(timeout=5), "Status reconciliation was not released"
        state.stages["brief"].status = StageStatus.AWAITING_REVIEW
        return True

    monkeypatch.setattr(projects, "_reopen_unapproved_brief", reconcile)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        inspection = asyncio.create_task(client.get("/api/projects/project-uuid/status"))
        rename = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            rename = asyncio.create_task(client.patch("/api/projects/project-uuid", json={"name": "New title"}))
            await asyncio.sleep(0.02)
            assert not rename.done()
        finally:
            release.set()
            status = await inspection
            renamed = await rename if rename is not None else None
        assert status.status_code == 200
        assert renamed is not None and renamed.status_code == 200
        latest = await client.get("/api/projects/project-uuid/status")
    assert latest.status_code == 200
    assert latest.json()["project_name"] == "New title"
    persisted = load_state(project_dir)
    assert persisted.project_name == "New title"
    assert persisted.stages["brief"].status == StageStatus.AWAITING_REVIEW
