"""Tests for event system (events.py)."""

import pytest

from novel_to_comic.events import EventCallback, make_progress, _NOOP


class TestNoop:
    def test_accepts_any_dict(self):
        _NOOP({"type": "stage_begin", "stage": "extract", "total": 10})
        _NOOP({"type": "log", "level": "info", "message": "hello"})
        _NOOP({})  # no error

    def test_returns_none(self):
        result = _NOOP({"type": "stage_begin"})
        assert result is None


class TestMakeProgress:
    def test_returns_silent_progress_when_on_event_provided(self):
        callback: EventCallback = lambda e: None
        p = make_progress(callback)
        # _SilentProgress is returned — all its methods are no-ops
        task_id = p.add_task("test")
        assert task_id is None
        p.advance(task_id)
        p.update(task_id)
        # no error

    def test_returns_rich_progress_when_on_event_is_none(self):
        p = make_progress(None)
        # Real Rich Progress has add_task returning an int
        task_id = p.add_task("test")
        assert isinstance(task_id, int)
        assert task_id >= 0


class TestSilentProgressContextManager:
    def test_context_manager_enter_exit(self):
        p = make_progress(lambda e: None)
        with p as progress:
            assert progress is p
        # no error on exit
