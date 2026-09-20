"""SPA fallback for client-side routes served by the production frontend mount."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.queue_fixtures import create_app

# web/dist is a built artifact (not always present in CI / fresh checkout),
# so skip these tests entirely when it isn't there.
DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
pytestmark = pytest.mark.skipif(
    not DIST.is_dir(),
    reason="web/dist build not present — run `npm run build` in web/ to exercise this",
)


@pytest.fixture(autouse=True)
def isolated_credit_lease_service(monkeypatch):
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: object())
    monkeypatch.setattr("novel_to_comic.server.credits.start_reservation_leases", lambda db: None)
    monkeypatch.setattr("novel_to_comic.server.credits.stop_reservation_leases", lambda: None)


def _client():
    # dev=False mounts the SPAStaticFiles frontend at "/".
    return TestClient(create_app(projects_dir=Path("/tmp/nonexistent-projects"), dev=False))


def test_client_side_route_falls_back_to_index_html():
    """A deep link like /login must return the SPA shell, not a 404 JSON."""
    with _client() as client:
        r = client.get("/login")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<div id=\"root\"" in r.text or "<body" in r.text  # the React mount point


def test_nested_client_side_route_falls_back_to_index_html():
    """Parametrised routes (/project/:id/draw) must also serve the SPA shell."""
    with _client() as client:
        r = client.get("/project/abc-123/draw")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_real_asset_with_extension_is_not_intercepted():
    """A missing asset (.js/.css/...) must still 404 — don't mask broken links."""
    with _client() as client:
        r = client.get("/assets/this-file-does-not-exist.js")
    assert r.status_code == 404


def test_api_404_is_not_intercepted_by_spa_fallback():
    """API routes live under /api/* and must never get the SPA shell."""
    with _client() as client:
        r = client.get("/api/this-route-does-not-exist")
    # No /api route matches, and the SPA fallback only applies to the static
    # mount — so FastAPI's default 404 JSON is correct here.
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
