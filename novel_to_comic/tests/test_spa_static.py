"""SPA fallback for client-side routes served by the production frontend mount."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

from novel_to_comic.server.app import SPAStaticFiles

from tests.queue_fixtures import create_app

# web/dist is a built artifact (not always present in CI / fresh checkout),
# so skip the app integration checks when it isn't there. The isolated static
# response checks below remain runnable without a frontend build.
DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


@pytest.fixture(autouse=True)
def isolated_credit_lease_service(monkeypatch):
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: object())
    monkeypatch.setattr("novel_to_comic.server.credits.start_reservation_leases", lambda db: None)
    monkeypatch.setattr("novel_to_comic.server.credits.stop_reservation_leases", lambda: None)


def _client():
    if not DIST.is_dir():
        pytest.skip("web/dist build not present — run `npm run build` in web/")
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


@pytest.fixture
def static_client(tmp_path):
    (tmp_path / "index.html").write_text('<html><div id="root"></div></html>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-AbCd12_3.js").write_text("console.log('app')")
    (tmp_path / "marketing").mkdir()
    (tmp_path / "marketing" / "poster.svg").write_text("<svg></svg>")
    (tmp_path / "marketing" / "hero.mp4").write_bytes(b"0123456789")
    return TestClient(Starlette(routes=[Mount("/", SPAStaticFiles(directory=tmp_path, html=True))]))


def test_fingerprinted_assets_are_immutable_even_on_revalidation(static_client):
    response = static_client.get("/assets/app-AbCd12_3.js")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    unchanged = static_client.get("/assets/app-AbCd12_3.js", headers={"If-None-Match": response.headers["etag"]})
    assert unchanged.status_code == 304
    assert unchanged.headers["cache-control"] == response.headers["cache-control"]


@pytest.mark.parametrize("path", ["/", "/index.html", "/login", "/project/example/pages"])
def test_shell_is_revalidated_across_routes(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    unchanged = static_client.get(path, headers={"If-None-Match": response.headers["etag"]})
    assert unchanged.status_code == 304
    assert unchanged.headers["cache-control"] == "no-cache"


def test_unfingerprinted_marketing_assets_have_a_short_cache(static_client):
    response = static_client.get("/marketing/poster.svg")
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_video_range_responses_keep_the_public_cache_policy(static_client):
    response = static_client.get("/marketing/hero.mp4", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"0123"
    assert response.headers["cache-control"] == "public, max-age=3600"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/marketing/missing.mp4", "/assets/missing.woff2"])
def test_missing_media_and_assets_never_return_the_html_shell(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 404
    assert "cache-control" not in response.headers


def test_unknown_document_is_a_real_404(static_client):
    response = static_client.get("/not-a-scenewright-route")
    assert response.status_code == 404
    assert "Page not found" in response.text
    assert response.headers["x-robots-tag"] == "noindex, follow"


@pytest.mark.parametrize("path", ["/login", "/signup", "/reset-password", "/auth/callback", "/account", "/credits", "/project/example/pages"])
def test_private_and_auth_routes_are_not_indexable(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, follow"


def test_prerender_manifest_serves_complete_public_documents_and_revalidates(tmp_path):
    import json
    (tmp_path / "index.html").write_text('<html><div id="root"></div></html>')
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "home.html").write_text('<html><h1>Comic studio for authors</h1></html>')
    (tmp_path / "public" / "pricing.html").write_text('<html><h1>Generation credits</h1></html>')
    (tmp_path / "public-pages.json").write_text(json.dumps({"/": "public/home.html", "/pricing": "public/pricing.html"}))
    client = TestClient(Starlette(routes=[Mount("/", SPAStaticFiles(directory=tmp_path, html=True))]))
    assert "Comic studio for authors" in client.get("/").text
    response = client.get("/pricing")
    assert response.status_code == 200
    assert "Generation credits" in response.text
    assert response.headers["cache-control"] == "no-cache"
    assert "x-robots-tag" not in response.headers
    unchanged = client.get("/pricing", headers={"If-None-Match": response.headers["etag"]})
    assert unchanged.status_code == 304
    assert unchanged.headers["cache-control"] == "no-cache"


@pytest.fixture
def public_static_client(tmp_path):
    (tmp_path / "index.html").write_text('<html><div id="root"></div></html>')
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "home.html").write_text('<html><div id="root" data-prerendered="true">Home</div></html>')
    (tmp_path / "public" / "pricing.html").write_text('<html><div id="root" data-prerendered="true">Pricing</div></html>')
    (tmp_path / "public-pages.json").write_text('{"/": "public/home.html", "/pricing": "public/pricing.html"}')
    return TestClient(Starlette(routes=[Mount("/", SPAStaticFiles(directory=tmp_path, html=True))]))


def test_signed_in_browsers_get_the_app_shell_at_root(public_static_client):
    anonymous = public_static_client.get("/")
    assert "data-prerendered" in anonymous.text
    assert anonymous.headers["vary"] == "Cookie"
    public_static_client.cookies.set("sw_signed_in", "1")
    signed_in = public_static_client.get("/")
    assert signed_in.status_code == 200
    assert "data-prerendered" not in signed_in.text
    assert signed_in.headers["cache-control"] == "no-cache"
    assert signed_in.headers["vary"] == "Cookie"
    # Other public pages stay public documents for everyone.
    assert "Pricing" in public_static_client.get("/pricing").text
