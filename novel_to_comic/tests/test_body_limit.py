import pytest

from novel_to_comic.server.body_limit import _body_cap_bytes


def test_import_story_body_is_capped_before_authentication(tmp_path):
    from fastapi.testclient import TestClient
    from novel_to_comic.server.app import create_app

    client = TestClient(create_app(tmp_path, dev=False))
    large = "x" * (3 * 1024 * 1024)
    assert client.post("/api/projects/import-story", json={"name": "x", "url_or_code": large}).status_code == 413
    assert client.post(
        "/api/projects/import-story",
        content=iter((b'{"url_or_code":"', large.encode(), b'"}')),
        headers={"Content-Type": "application/json"},
    ).status_code == 413


def test_novel_upload_uses_its_larger_multipart_envelope(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")
    monkeypatch.setenv("CANARY_MAX_UPLOAD_MB", "10")

    assert _body_cap_bytes("/api/projects/", "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes("/api/projects/source-preview", "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes("/api/projects/import-story", "POST") == 2 * 1024 * 1024


@pytest.mark.parametrize("path,method", [
    ("/api/projects/my-book/parts", "POST"),
    ("/api/projects/my-book/parts/", "POST"),
    ("/api/projects/my-book/parts/part_0002/text", "PUT"),
    ("/api/projects/my-book/parts/part_0002/text/", "PUT"),
])
def test_part_sources_use_the_configured_upload_envelope(monkeypatch, path, method):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")
    monkeypatch.setenv("CANARY_MAX_UPLOAD_MB", "50")

    assert _body_cap_bytes(path, method) == 51 * 1024 * 1024


@pytest.mark.parametrize("path,method", [
    ("/api/projects/my-book/parts/export", "POST"),
    ("/api/projects/my-book/parts/part_0002/split", "POST"),
    ("/api/projects/my-book/parts/part_0002/text", "POST"),
    ("/api/projects/my-book/parts", "PUT"),
    ("/api/projects/my-book/parts/part_0002", "PATCH"),
])
def test_part_json_actions_keep_the_generic_cap(monkeypatch, path, method):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")

    assert _body_cap_bytes(path, method) == 2 * 1024 * 1024


def test_style_direction_upload_has_preparser_multipart_envelope(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")

    assert _body_cap_bytes("/api/projects/my-book/styles/direction", "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes("/api/projects/my-book/styles/direction/", "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes("/api/projects/my-book/styles/direction", "PUT") == 2 * 1024 * 1024


def test_other_routes_keep_the_generic_body_cap(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")

    assert _body_cap_bytes("/api/projects/my-book/styles/validation", "POST") == 2 * 1024 * 1024


@pytest.mark.parametrize("path", ["/api/projects/my-book/styles/direction", "/api/projects/my-book/cast/reference-uploads"])
def test_image_upload_routes_allow_one_reference_image(monkeypatch, path):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")

    assert _body_cap_bytes(path, "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes(path, "GET") == 2 * 1024 * 1024
