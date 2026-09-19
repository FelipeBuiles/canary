"""Exercise the actual API helpers, independently of Supabase/provider services."""
import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile


@pytest.mark.parametrize("slug", ["../victim/story", "/tmp/foreign", "..", ".private"])
def test_project_dependency_rejects_a_poisoned_owned_row(tmp_path, monkeypatch, slug):
    from novel_to_comic.server import deps

    victim = tmp_path / "victim" / "story"
    victim.mkdir(parents=True)
    (victim / "state.json").write_text('{"project_name":"private"}')
    monkeypatch.setattr(deps, "_db_query_projects", lambda *args: SimpleNamespace(data=[{"name": slug}]))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(projects_dir=tmp_path)))
    with pytest.raises(HTTPException) as caught:
        deps.get_project_dir("owned-row", request, "account")
    assert caught.value.status_code == 404
    assert (victim / "state.json").exists()


def test_listing_does_not_read_foreign_state_even_for_an_owned_row(tmp_path, monkeypatch):
    from novel_to_comic.server.routers import projects

    victim = tmp_path / "victim" / "story"
    victim.mkdir(parents=True)
    (victim / "state.json").write_text('{"project_name":"private"}')
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "owned-row", "name": "../victim/story", "created_at": "2026-09-19"}],
    )
    monkeypatch.setattr(projects, "get_db", lambda: db)
    read = MagicMock(side_effect=AssertionError("foreign state must not be read"))
    monkeypatch.setattr(projects, "load_state", read)
    assert projects.list_projects(SimpleNamespace(), tmp_path, "account") == []
    read.assert_not_called()


@pytest.mark.parametrize("key", [
    "litellm_base_url", "litellm_api_key", "ai_bill_failed_requests",
    "mock_mode", "mock_model_base_url", "google_use_vertex_ai",
    "google_cloud_project", "google_cloud_location",
])
def test_creation_cannot_override_operator_configuration(tmp_path, monkeypatch, key):
    from novel_to_comic.server import account_models

    overlay = MagicMock()
    monkeypatch.setattr(account_models, "account_config", overlay)
    with pytest.raises(ValueError, match="Operator configuration"):
        account_models.creation_config({key: "untrusted"}, tmp_path, "account")
    overlay.assert_not_called()


def test_account_settings_cannot_follow_a_sibling_account_symlink(tmp_path):
    from novel_to_comic.server import account_models

    victim = tmp_path / "victim"
    victim.mkdir()
    (tmp_path / "account").symlink_to(victim, target_is_directory=True)
    with pytest.raises(ValueError):
        account_models._account_dir(tmp_path, "account")


def test_upload_rejects_account_alias_before_staging(tmp_path, monkeypatch):
    from novel_to_comic.server import account_models
    from novel_to_comic.server.routers import projects

    victim = tmp_path / "victim"
    victim.mkdir()
    (tmp_path / "account").symlink_to(victim, target_is_directory=True)
    monkeypatch.setattr(projects, "_count_user_projects", lambda user: 0)
    monkeypatch.setattr(account_models, "creation_config", lambda *args: SimpleNamespace())
    upload = UploadFile(filename="source.txt", file=BytesIO(b"sample story"))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(projects.create_project.__wrapped__(
            SimpleNamespace(), file=upload, name="story", config_overrides=None,
            projects_dir=tmp_path, user_id="account",
        ))
    assert caught.value.status_code == 409
    assert list(victim.iterdir()) == []


def test_invalid_import_code_is_rejected_before_network(tmp_path, monkeypatch):
    from novel_to_comic.server.routers import projects

    monkeypatch.setattr(projects, "_count_user_projects", lambda user: 0)
    download = AsyncMock()
    monkeypatch.setattr(projects, "_download_remote_story", download)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(projects.import_short_story.__wrapped__(
            SimpleNamespace(), projects.ImportStoryRequest(name="story", url_or_code="bad?query"),
            projects_dir=tmp_path, user_id="account",
        ))
    assert caught.value.status_code == 400
    download.assert_not_called()
