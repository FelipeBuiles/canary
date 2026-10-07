"""Tests for the Labs feature gate (CANARY_LABS_ENABLED).

Labs is an experimentation surface that shrinks the public attack surface when
disabled. The router is conditionally included by ``create_app`` based on the
env flag — these tests lock that behaviour in so a refactor can't silently
re-expose it.
"""

from pathlib import Path

import pytest

from tests.queue_fixtures import create_app
from novel_to_comic.server.app import _labs_enabled


def _has_labs_routes(app) -> bool:
    # Included routers are lazy in newer FastAPI; inspect the public schema.
    return any(path.startswith("/api/labs") for path in app.openapi()["paths"])


def test_labs_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_LABS_ENABLED", raising=False)
    app = create_app(Path(str(tmp_path)), dev=True)
    assert not _has_labs_routes(app), (
        "Labs must default OFF — it bills provider quota directly and is not "
        "credit-gated, so it should not ship enabled without an explicit opt-in."
    )


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE"])
def test_labs_disabled_when_flag_false(monkeypatch, value):
    _original_process(monkeypatch, CANARY_ENV="development")
    monkeypatch.setenv("CANARY_LABS_ENABLED", value)
    assert not _labs_enabled(), (
        f"Labs should be hidden when CANARY_LABS_ENABLED={value!r}"
    )


def _original_process(monkeypatch, **settings):
    from types import MappingProxyType

    from novel_to_comic import codex_dev

    process = dict.fromkeys(codex_dev._PROCESS)
    process.update(settings)
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(process))


@pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
def test_labs_enabled_when_flag_true(monkeypatch, value):
    _original_process(monkeypatch, CANARY_ENV="development")
    monkeypatch.setenv("CANARY_LABS_ENABLED", value)
    assert _labs_enabled()


@pytest.mark.parametrize("enabled", [False, True])
def test_labs_router_mount_matches_gate(monkeypatch, tmp_path, enabled):
    _original_process(monkeypatch, CANARY_ENV="development")
    monkeypatch.setenv("CANARY_LABS_ENABLED", str(enabled))
    app = create_app(Path(str(tmp_path)), dev=True)
    assert _has_labs_routes(app) is enabled


def test_labs_flag_cannot_enable_labs_outside_original_process_development(monkeypatch, tmp_path):
    _original_process(monkeypatch, CANARY_ENV="production")
    monkeypatch.setenv("CANARY_LABS_ENABLED", "true")
    app = create_app(Path(str(tmp_path)), dev=True)
    assert not _has_labs_routes(app)


def _labs_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from novel_to_comic.server.auth import get_current_user

    _original_process(monkeypatch, CANARY_ENV="development")
    monkeypatch.setenv("CANARY_LABS_ENABLED", "true")
    app = create_app(Path(str(tmp_path)), dev=True)
    app.dependency_overrides[get_current_user] = lambda: "owner"
    return TestClient(app)


def test_labs_rejects_bad_runs_and_paths_before_any_spend(monkeypatch, tmp_path):
    client = _labs_client(monkeypatch, tmp_path)

    assert client.get("/api/labs/runs").json() == {"runs": []}
    assert client.post("/api/labs/runs", json={"kind": "panels"}).status_code == 400
    assert client.post("/api/labs/runs", json={
        "kind": "image_compare", "project": "missing", "items": ["page:1"],
        "arms": [{"target": "sunburst-openai", "prompt": "production"}, {"target": "sunburst-fal", "prompt": "production"}],
    }).status_code == 400
    assert client.post("/api/labs/image-compare/preview", json={"project": "../x", "item": "page:1", "arms": []}).status_code == 400
    assert client.post("/api/labs/runs", json={
        "kind": "stage_models", "project": "../other", "phases": ["adapt_plan"],
        "models": ["claude-opus-5-5", "claude-sonnet-5-5"],
    }).status_code == 400
    assert client.get("/api/labs/runs/not-a-run").status_code == 400
    assert client.get("/api/labs/runs/20260929-000000-abcdef/files/../../../secret.json").status_code in {400, 404}


def test_labs_run_files_never_resolve_outside_their_run(tmp_path):
    import pytest as _pytest

    from novel_to_comic.labs import storage

    run = storage.create_run(tmp_path, kind="image_compare", label="t", spec={})
    assert storage.run_file(tmp_path, run["run_id"], "images/a.png").is_relative_to(tmp_path)
    for escape in ("../other/run.json", "/etc/passwd", "images/../../x"):
        with _pytest.raises(ValueError):
            storage.run_file(tmp_path, run["run_id"], escape)
    with _pytest.raises(ValueError):
        storage.run_dir(tmp_path, "../x")


def test_labs_reasoning_is_validated_before_creating_run(monkeypatch, tmp_path):
    from novel_to_comic.server.routers import labs
    from novel_to_comic.labs import stage_models, storage
    client = _labs_client(monkeypatch, tmp_path)
    source = tmp_path / "owner" / "story"
    source.mkdir(parents=True)
    monkeypatch.setattr(stage_models, "validate_spec", lambda *args: None)
    monkeypatch.setattr(stage_models, "estimate_usd", lambda source, phases, models: {model: None for model in models})
    dispatched = []
    def start(request, root, run_id, coroutine):
        dispatched.append(run_id)
        coroutine.close()
    monkeypatch.setattr(labs, "_start", start)
    body = {"kind": "stage_models", "project": "story", "phases": ["extract_brief"],
            "models": ["gpt-6-sol", "mimo-v2.6-pro"],
            "reasoning_efforts": {"mimo-v2.6-pro": {"extract": "medium"}}}
    assert client.post("/api/labs/runs", json=body).status_code == 400
    assert client.post("/api/labs/stage-models/estimate", json=body).status_code == 400
    assert not dispatched
    assert not storage.list_runs(tmp_path / "owner")
    body["reasoning_efforts"] = {"mimo-v2.6-pro": {"extract": "enabled"}, "gpt-6-sol": {"brief": "low"}}
    result = client.post("/api/labs/runs", json=body)
    assert result.status_code == 200
    selected = result.json()["spec"]["reasoning_efforts"]
    assert selected == {"mimo-v2.6-pro": {"extract": "enabled", "brief": "none"},
                        "gpt-6-sol": {"extract": "medium", "brief": "low"}}
    assert dispatched == [result.json()["run_id"]]


def test_labs_source_files_use_slugs_and_stay_in_owned_project(monkeypatch, tmp_path):
    client = _labs_client(monkeypatch, tmp_path)
    project = tmp_path / "owner" / "elm-and-keep"
    (project / "pages").mkdir(parents=True)
    (project / "state.json").write_text("{}")
    (project / "pages" / "page.png").write_bytes(b"image")
    (project / "config.yaml").write_text("secret")
    (project / ".private").write_text("secret")
    other = tmp_path / "other" / "story"
    other.mkdir(parents=True)
    (other / "state.json").write_text("{}")
    (other / "page.png").write_bytes(b"private")
    (project / "escape.png").symlink_to(other / "page.png")
    (tmp_path / "owner" / "linked-project").symlink_to(other)

    base = "/api/labs/projects/elm-and-keep/files/"
    response = client.get(base + "pages/page.png")
    assert response.status_code == 200
    assert response.content == b"image"
    assert response.headers["cache-control"] == "private, max-age=60"
    assert client.get(base + "missing.png").status_code == 404
    for path in ("config.yaml", ".private", "escape.png", "pages/%2E%2E/%2E%2E/secret"):
        assert client.get(base + path).status_code == 403
    assert client.get("/api/labs/projects/story/files/page.png").status_code == 404
    assert client.get("/api/labs/projects/linked-project/files/page.png").status_code == 403
