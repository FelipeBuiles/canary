"""Provider-free local marketing transport and production exclusion checks."""

import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.server.routers import marketing


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CANARY_OPS_TOKEN", "test-ops-token")
    app = FastAPI()
    app.include_router(marketing.router, prefix="/api/ops/backoffice/marketing")
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


HEADERS = {"X-Canary-Ops-Token": "test-ops-token"}
BASE = "/api/ops/backoffice/marketing"


def test_requires_operator_token(client):
    assert client.get(f"{BASE}/snapshot").status_code == 401
    assert client.post(f"{BASE}/transition", json={}).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "remote.example"},
        {"forwarded": "for=127.0.0.1"},
        {"x-forwarded-for": "127.0.0.1"},
        {"x-forwarded-host": "localhost"},
        {"x-forwarded-proto": "http"},
    ],
)
def test_rejects_forwarded_and_nonlocal_hosts(client, headers):
    assert (
        client.get(f"{BASE}/snapshot", headers={**HEADERS, **headers}).status_code
        == 403
    )
    assert (
        client.post(
            f"{BASE}/transition", headers={**HEADERS, **headers}, json={}
        ).status_code
        == 403
    )


def test_rejects_nonlocal_client(monkeypatch):
    monkeypatch.setenv("CANARY_OPS_TOKEN", "test-ops-token")
    app = FastAPI()
    app.include_router(marketing.router, prefix=BASE)
    with TestClient(
        app, base_url="http://localhost", client=("192.0.2.1", 50000)
    ) as client:
        assert client.get(f"{BASE}/snapshot", headers=HEADERS).status_code == 403


def test_real_node_bridge_reads_local_workspace(client):
    result = client.get(f"{BASE}/snapshot", headers=HEADERS)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    assert isinstance(result.json()["drafts"], list)
    assert result.json()["facts"]
    assert (
        client.post(f"{BASE}/transition", json={}, headers=HEADERS).status_code == 400
    )


def test_transition_bounds_requests_and_requires_json(client):
    assert (
        client.post(f"{BASE}/transition", headers=HEADERS, content="{}").status_code
        == 415
    )
    assert (
        client.post(
            f"{BASE}/transition", headers=HEADERS, json={"path": "x" * 70000}
        ).status_code
        == 413
    )
    assert (
        client.post(
            f"{BASE}/transition",
            headers={**HEADERS, "content-type": "application/json"},
            content="{",
        ).status_code
        == 422
    )


def test_missing_tooling_returns_setup_instruction(client, monkeypatch, tmp_path):
    monkeypatch.setattr(marketing, "CANARY_ROOT", tmp_path)
    result = client.get(f"{BASE}/snapshot", headers=HEADERS)
    assert result.status_code == 503
    assert "npm ci" in result.json()["detail"]


@pytest.mark.parametrize(
    ("dev", "environment", "present"),
    [
        (True, "dev", True),
        (False, "dev", False),
        (True, "production", False),
        (False, "production", False),
    ],
)
def test_routes_registered_only_in_local_development(
    tmp_path, monkeypatch, dev, environment, present
):
    from novel_to_comic.server.app import create_app

    monkeypatch.setenv("CANARY_ENV", environment)
    app = create_app(tmp_path, dev=dev)
    assert (f"{BASE}/snapshot" in app.openapi()["paths"]) is present
    assert (f"{BASE}/transition" in app.openapi()["paths"]) is present


def test_bridge_transitions_fixture_without_touching_live_drafts(
    client, monkeypatch, tmp_path
):
    source = marketing.CANARY_ROOT / "marketing"
    root = tmp_path / "marketing"
    (root / "knowledge").mkdir(parents=True)
    (root / "drafts/blog").mkdir(parents=True)
    for name in ("src", "scripts"):
        shutil.copytree(source / name, root / name)
    shutil.copyfile(source / "package.json", root / "package.json")
    (root / "node_modules").symlink_to(
        source / "node_modules", target_is_directory=True
    )
    (root / "knowledge/facts.yaml").write_text("[]")
    (root / "knowledge/claims-policy.md").write_text("Review copy before posting.")
    (root / "knowledge/canary-manifest.json").write_text(
        json.dumps({"include": ["PRODUCT.md"], "exclude": []})
    )
    (root / "knowledge/canary.lock.json").write_text(
        json.dumps({"sha": "fixture", "synced": "2026-10-27", "files": {}})
    )
    path = "drafts/blog/example.md"
    draft = root / path
    draft.write_text(
        "---\nkind: post\nchannel: blog\ntitle: Fixture\nfacts: []\nsources: []\ncreated: 2026-10-27\nstatus: draft\n---\n\nFixture copy\n"
    )
    monkeypatch.setattr(marketing, "CANARY_ROOT", tmp_path)
    snapshot = client.get(f"{BASE}/snapshot", headers=HEADERS)
    assert snapshot.status_code == 200, snapshot.text
    view = snapshot.json()["drafts"][0]
    payload = {
        "path": path,
        "revision": view["revision"],
        "transition": {"to": "approved"},
    }
    response = client.post(f"{BASE}/transition", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "status: approved" in draft.read_text()
    assert (
        client.post(f"{BASE}/transition", headers=HEADERS, json=payload).status_code
        == 409
    )
