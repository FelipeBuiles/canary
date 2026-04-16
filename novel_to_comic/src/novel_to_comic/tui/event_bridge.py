"""Bridge between pipeline stage events and Textual Messages.

Stage events (dicts from the on_event callback) are translated into typed
Textual Messages that screens/widgets can react to without coupling to
the raw event schema.
"""

from __future__ import annotations

from textual.message import Message


class StageBegin(Message):
    """A pipeline stage has started."""

    def __init__(self, stage: str, total: int) -> None:
        super().__init__()
        self.stage = stage
        self.total = total


class StageProgress(Message):
    """Progress update within a pipeline stage."""

    def __init__(self, stage: str, done: int, total: int) -> None:
        super().__init__()
        self.stage = stage
        self.done = done
        self.total = total


class StageComplete(Message):
    """A pipeline stage has finished."""

    def __init__(self, stage: str, done: int, total: int) -> None:
        super().__init__()
        self.stage = stage
        self.done = done
        self.total = total


class StageFail(Message):
    """A pipeline stage has failed."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__()
        self.stage = stage
        self.message = message


class LogEvent(Message):
    """A log message from a pipeline stage."""

    def __init__(self, stage: str, level: str, message: str) -> None:
        super().__init__()
        self.stage = stage
        self.level = level
        self.message = message


# Map raw event dicts → Textual Message instances
_EVENT_MAP = {
    "stage_begin": StageBegin,
    "stage_progress": StageProgress,
    "stage_complete": StageComplete,
    "stage_fail": StageFail,
    "log": LogEvent,
}


def event_to_message(event: dict) -> Message | None:
    """Convert a raw pipeline event dict to a Textual Message."""
    evt_type = event.get("type")
    msg_cls = _EVENT_MAP.get(evt_type)
    if msg_cls is None:
        return None
    # Strip "type" key — the rest are constructor kwargs
    kwargs = {k: v for k, v in event.items() if k != "type"}
    try:
        return msg_cls(**kwargs)
    except TypeError:
        return None
