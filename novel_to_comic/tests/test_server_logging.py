from types import SimpleNamespace

from novel_to_comic.server.logging import _should_log_request


def _request(path: str, method: str = "GET"):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def test_non_static_failures_are_logged():
    request = _request("/api/projects/demo/images")

    assert _should_log_request(request, 404, 12)


def test_missing_draw_file_failures_are_suppressed():
    request = _request("/api/projects/demo/files/draw/scene_001/panel_001.png")

    assert not _should_log_request(request, 404, 12)


def test_not_yet_generated_style_sample_failures_are_suppressed():
    sample = _request("/api/projects/demo/files/samples/style_1.png")
    metadata = _request("/api/projects/demo/files/samples/style_1.png.meta.json")

    assert not _should_log_request(sample, 404, 12)
    assert not _should_log_request(metadata, 404, 12)


def test_no_active_event_stream_is_suppressed_but_server_failure_is_logged():
    request = _request("/api/projects/demo/events")

    assert not _should_log_request(request, 404, 12)
    assert _should_log_request(request, 500, 12)
