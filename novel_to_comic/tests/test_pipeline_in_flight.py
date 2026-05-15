"""Tests for the on_event wrapper that maintains app.state.draw_in_flight."""

import asyncio
from types import SimpleNamespace

from novel_to_comic.server.routers.pipeline import _wrap_on_event


def _new_app_state():
    return SimpleNamespace(draw_in_flight={})


def test_panel_start_appends_to_in_flight():
    queue: asyncio.Queue = asyncio.Queue()
    app_state = _new_app_state()
    handler = _wrap_on_event(queue, app_state, "user-1/proj-a")

    handler({
        "type": "panel_start", "stage": "draw",
        "scene_id": "scene_03", "panel_number": 7,
        "started_at": "2026-05-15T18:42:11+00:00",
    })

    assert app_state.draw_in_flight["user-1/proj-a"] == [
        {"scene_id": "scene_03", "panel_number": 7,
         "started_at": "2026-05-15T18:42:11+00:00"},
    ]
    assert queue.get_nowait()["type"] == "panel_start"


def test_panel_done_removes_matching_entry():
    queue: asyncio.Queue = asyncio.Queue()
    app_state = _new_app_state()
    handler = _wrap_on_event(queue, app_state, "k")

    handler({"type": "panel_start", "stage": "draw",
             "scene_id": "s_1", "panel_number": 1, "started_at": "t1"})
    handler({"type": "panel_start", "stage": "draw",
             "scene_id": "s_1", "panel_number": 2, "started_at": "t2"})
    # Drain SSE queue noise so only the relevant assertions remain.
    while not queue.empty():
        queue.get_nowait()

    handler({"type": "panel_done", "stage": "draw",
             "scene_id": "s_1", "panel_number": 1,
             "status": "ok", "duration_ms": 1000, "error": None})

    assert app_state.draw_in_flight["k"] == [
        {"scene_id": "s_1", "panel_number": 2, "started_at": "t2"},
    ]


def test_stage_complete_clears_in_flight():
    queue: asyncio.Queue = asyncio.Queue()
    app_state = _new_app_state()
    handler = _wrap_on_event(queue, app_state, "k")
    handler({"type": "panel_start", "stage": "draw",
             "scene_id": "s", "panel_number": 1, "started_at": "t"})
    handler({"type": "stage_complete", "stage": "draw", "done": 1, "total": 1})
    assert "k" not in app_state.draw_in_flight


def test_stage_fail_clears_in_flight():
    queue: asyncio.Queue = asyncio.Queue()
    app_state = _new_app_state()
    handler = _wrap_on_event(queue, app_state, "k")
    handler({"type": "panel_start", "stage": "draw",
             "scene_id": "s", "panel_number": 1, "started_at": "t"})
    handler({"type": "stage_fail", "stage": "draw", "message": "boom"})
    assert "k" not in app_state.draw_in_flight


def test_non_draw_panel_events_ignored_by_in_flight_map():
    queue: asyncio.Queue = asyncio.Queue()
    app_state = _new_app_state()
    handler = _wrap_on_event(queue, app_state, "k")
    # Hypothetical event from a different stage — should not pollute the
    # draw in-flight map. (Stages other than draw don't emit panel_*
    # today; this guards against future drift.)
    handler({"type": "panel_start", "stage": "cast",
             "scene_id": "s", "panel_number": 1, "started_at": "t"})
    assert app_state.draw_in_flight == {}


def test_all_events_are_pushed_to_queue():
    queue: asyncio.Queue = asyncio.Queue()
    app_state = _new_app_state()
    handler = _wrap_on_event(queue, app_state, "k")
    handler({"type": "stage_progress", "stage": "draw", "done": 1, "total": 5})
    handler({"type": "log", "stage": "draw", "level": "info", "message": "hi"})
    assert queue.qsize() == 2
