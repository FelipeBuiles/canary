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
    monkeypatch.setattr(stage_models, "estimate_stages_usd", lambda source, models: None)
    dispatched = []
    def start(request, root, run_id, coroutine):
        dispatched.append(run_id)
        coroutine.close()
    monkeypatch.setattr(labs, "_start", start)
    body = {"kind": "stage_models", "project": "story", "phases": ["extract_brief"],
            "arms": [{"id": "arm-1", "model": "gpt-6-sol"},
                     {"id": "arm-2", "model": "mimo-v2.6-pro", "reasoning_efforts": {"extract": "medium"}}]}
    assert client.post("/api/labs/runs", json=body).status_code == 400
    assert client.post("/api/labs/stage-models/estimate", json=body).status_code == 400
    assert not dispatched
    assert not storage.list_runs(tmp_path / "owner")
    body["arms"][0]["reasoning_efforts"] = {"brief": "low"}
    body["arms"][1]["reasoning_efforts"] = {"extract": "enabled"}
    result = client.post("/api/labs/runs", json=body)
    assert result.status_code == 200
    selected = result.json()["spec"]["arms"]
    assert selected == [
        {"id": "arm-1", "model": "gpt-6-sol", "stage_models": {"extract": "gpt-6-sol", "brief": "gpt-6-sol"},
         "reasoning_efforts": {"extract": "medium", "brief": "low"}},
        {"id": "arm-2", "model": "mimo-v2.6-pro", "stage_models": {"extract": "mimo-v2.6-pro", "brief": "mimo-v2.6-pro"},
         "reasoning_efforts": {"extract": "enabled", "brief": "none"}},
    ]
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


def test_retry_dispatches_failed_text_arms_to_the_stage_model_runner(monkeypatch, tmp_path):
    from novel_to_comic.server.routers import labs
    from novel_to_comic.labs import stage_models, storage
    client = _labs_client(monkeypatch, tmp_path)
    root = tmp_path / "owner"
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={"project": "story"})
    storage.write_cell(root, run["run_id"], "extract_brief.a", {"status": "failed", "model": "a"})
    storage.write_cell(root, run["run_id"], "extract_brief.b", {"status": "ok", "model": "b"})
    storage.update_run(root, run["run_id"], status="complete")
    dispatched = []
    def start(request, root, run_id, coroutine, cells=None):
        dispatched.append((coroutine.cr_code.co_filename.rsplit("/", 1)[-1], coroutine.cr_code.co_name))
        coroutine.close()
    monkeypatch.setattr(labs, "_start", start)

    url = f"/api/labs/runs/{run['run_id']}/retry"
    assert client.post(url, json={"cells": ["extract_brief.b"]}).status_code == 400
    result = client.post(url, json={})
    assert result.status_code == 200 and result.json()["cells"] == ["extract_brief.a"]
    assert dispatched == [("stage_models.py", "retry")]
    assert storage.read_run(root, run["run_id"])["status"] == "running"


def test_failed_arms_retry_side_by_side_but_never_twice_at_once(monkeypatch, tmp_path):
    import asyncio
    from novel_to_comic.labs import stage_models, storage
    root = tmp_path / "owner"
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={"project": "story"})
    for cell in ("full.a", "full.b"):
        storage.write_cell(root, run["run_id"], cell, {"status": "failed", "model": cell})
    storage.update_run(root, run["run_id"], status="complete")
    release: dict[str, asyncio.Event] = {}

    async def retry(user_root, run_id, cells):
        (cell,) = cells
        release[cell["cell_id"]] = event = asyncio.Event()
        await event.wait()
        storage.write_cell(user_root, run_id, cell["cell_id"], {"status": "ok", "model": cell["model"]})
    monkeypatch.setattr(stage_models, "retry", retry)

    async def finish(cell):
        while cell not in release:
            await asyncio.sleep(0)
        release[cell].set()
        for _ in range(20):
            await asyncio.sleep(0)

    url = f"/api/labs/runs/{run['run_id']}/retry"
    with _labs_client(monkeypatch, tmp_path) as client:
        assert client.post(url, json={"cells": ["full.a"]}).json()["cells"] == ["full.a"]
        assert client.post(url, json={"cells": ["full.a"]}).status_code == 409
        assert client.post(url, json={}).json()["cells"] == ["full.b"], "retry-all skips a cell already rerunning"
        assert storage.read_run(root, run["run_id"])["status"] == "running"
        client.portal.call(finish, "full.a")
        assert storage.read_run(root, run["run_id"])["status"] == "running", "full.b is still retrying"
        client.portal.call(finish, "full.b")
        assert storage.read_run(root, run["run_id"])["status"] == "complete"


def test_cells_a_restart_interrupted_become_retryable(monkeypatch, tmp_path):
    from novel_to_comic.labs import stage_models, storage
    client = _labs_client(monkeypatch, tmp_path)
    root = tmp_path / "owner"
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={"project": "story"})
    storage.write_cell(root, run["run_id"], "full.a", {"status": "running", "model": "a", "stages": [{"stage": "extract"}]})
    storage.write_cell(root, run["run_id"], "full.b", {"status": "ok", "model": "b"})

    detail = client.get(f"/api/labs/runs/{run['run_id']}").json()

    assert detail["status"] == "interrupted"
    cells = {cell["cell_id"]: cell for cell in detail["cells"]}
    assert cells["full.a"]["status"] == "failed" and cells["full.a"]["stages"] == [{"stage": "extract"}]
    assert cells["full.b"]["status"] == "ok"
    assert [cell["cell_id"] for cell in stage_models.failed_cells(root, run["run_id"], None)] == ["full.a"]


def test_labs_duplicate_models_snapshot_and_estimate_every_arm(monkeypatch, tmp_path):
    from novel_to_comic.server.routers import labs
    from novel_to_comic.labs import stage_models
    client = _labs_client(monkeypatch, tmp_path)
    (tmp_path / "owner/story").mkdir(parents=True)
    monkeypatch.setattr(stage_models, "validate_spec", lambda *args: None)
    monkeypatch.setattr(stage_models, "estimate_stages_usd", lambda source, models: 0.5)
    dispatched = []
    def start(request, root, run_id, coroutine):
        dispatched.append(run_id)
        coroutine.close()
    monkeypatch.setattr(labs, "_start", start)
    body = {"kind": "stage_models", "project": "story", "phases": ["extract_brief"], "arms": [
        {"id": "low", "model": "gpt-6-sol", "reasoning_efforts": {"extract": "low"}},
        {"id": "high", "model": "gpt-6-sol", "reasoning_efforts": {"extract": "high"}},
    ]}
    estimate = client.post("/api/labs/stage-models/estimate", json=body)
    assert estimate.status_code == 200
    assert estimate.json()["estimated_cost_usd"] == {"low": 0.5, "high": 0.5}
    run = client.post("/api/labs/runs", json=body)
    assert run.status_code == 200
    assert [arm["reasoning_efforts"]["extract"] for arm in run.json()["spec"]["arms"]] == ["low", "high"]
    assert run.json()["spec"]["estimated_cost_usd"] == estimate.json()["estimated_cost_usd"]
    assert len(dispatched) == 1
    body["arms"][1]["id"] = "low"
    assert client.post("/api/labs/runs", json=body).status_code == 400
    assert client.post("/api/labs/stage-models/estimate", json=body).status_code == 400
    assert len(dispatched) == 1
