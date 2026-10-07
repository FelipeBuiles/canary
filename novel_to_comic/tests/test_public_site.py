"""Built HTML is the anonymous crawler contract, not just a React unit render."""
import json
import re
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from novel_to_comic.server.app import SPAStaticFiles
from novel_to_comic.server.routers.billing import CREDIT_PACKAGES

DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
pytestmark = pytest.mark.skipif(
    not DIST.is_dir() or not (DIST / "public-pages.json").exists(),
    reason="Build the web frontend first (source-only backend checks hide it)",
)


@pytest.fixture
def public_site():
    return TestClient(Starlette(routes=[Mount("/", SPAStaticFiles(directory=DIST, html=True))]))


@pytest.mark.parametrize("path,language", [("/", "en"), ("/es", "es"), ("/fr", "fr"), ("/how-it-works", "en"),
    ("/pricing", "en"), ("/about", "en"), ("/guides/turn-a-novel-into-a-comic", "en"),
    ("/examples/kaitlin-out-of-space", "en"), ("/legal/terms", "en"), ("/legal/privacy", "en"), ("/legal/acceptable-use", "en")])
def test_initial_public_html_is_complete_and_has_unique_metadata(public_site, path, language):
    response = public_site.get(path)
    body = response.text
    assert response.status_code == 200
    assert body.count("<title>") == 1
    assert body.count('rel="canonical"') == 1
    assert body.count('name="description"') == 1
    assert f'href="https://scenewright.ink{path}"' in body
    assert f'<html lang="{language}">' in body
    assert '<h1' in body and len(re.findall(r'<p\b', body)) >= 4
    assert 'data-prerendered="true"' in body
    assert '<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">' in body
    locale = {"en": "en_US", "es": "es_ES", "fr": "fr_FR"}[language]
    assert f'<meta property="og:locale" content="{locale}">' in body
    assert "x-robots-tag" not in response.headers
    schema = json.loads(re.search(r'id="public-schema"[^>]*>(.*?)</script>', body, re.S).group(1))
    assert schema["@context"] == "https://schema.org"
    assert not any("aggregateRating" in item or "review" in item for item in schema["@graph"])
    if path in {"/", "/es", "/fr"}:
        for locale, target in (("en", "/"), ("es", "/es"), ("fr", "/fr"), ("x-default", "/")):
            assert f'hreflang="{locale}" href="https://scenewright.ink{target}"' in body
        assert re.search(r'<link rel="stylesheet" href="/assets/HomePage-[^"]+\.css">', body)
        assert '<video' not in body
        for image in re.findall(r'<img\b[^>]*>', body):
            assert re.search(r'\bwidth="[1-9]\d*"', image), image
            assert re.search(r'\bheight="[1-9]\d*"', image), image


def test_built_pricing_agrees_with_the_billing_contract(public_site):
    body = public_site.get("/pricing").text
    rows = re.findall(r'<tr[^>]*>.*?<td[^>]*>([^<]*)</td>.*?<td[^>]*>([^<]*)</td>.*?</tr>', body, re.S)
    assert rows == [(f'{pack["credits"]:,}', 'US$' + f'{pack["price_cents"] / 100:g}') for pack in CREDIT_PACKAGES.values()]


def test_card_and_public_assets_exist_and_aliases_redirect(public_site):
    response = public_site.get("/marketing/scenewright-social.png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    from PIL import Image
    from io import BytesIO
    assert Image.open(BytesIO(response.content)).size == (1200, 630)
    assert public_site.get("/marketing/masque-flipbook-poster.webp").headers["content-type"] == "image/webp"
    alias = public_site.get("/public/home.html", follow_redirects=False)
    assert alias.status_code == 308 and alias.headers["location"] == "/"
    for path in json.loads((DIST / "public-pages.json").read_text()):
        document = public_site.get(path).text
        for asset in set(re.findall(r'(?:src|href)="(/assets/[^" ]+)"', document)):
            assert public_site.get(asset).status_code == 200, asset
