from novel_to_comic.server.body_limit import _body_cap_bytes


def test_style_direction_upload_has_preparser_multipart_envelope(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")

    assert _body_cap_bytes("/api/projects/my-book/styles/direction", "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes("/api/projects/my-book/styles/direction/", "POST") == 11 * 1024 * 1024
    assert _body_cap_bytes("/api/projects/my-book/styles/direction", "PUT") == 2 * 1024 * 1024


def test_other_routes_keep_the_generic_body_cap(monkeypatch):
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "2")

    assert _body_cap_bytes("/api/projects/my-book/styles/validation", "POST") == 2 * 1024 * 1024
