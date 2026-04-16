"""Scrollable log viewer that consumes log events."""

from __future__ import annotations

from textual.widgets import RichLog

from ..event_bridge import LogEvent

_LEVEL_STYLES = {
    "info": "white",
    "warn": "yellow",
    "error": "bold red",
    "dim": "dim",
    "bold": "bold",
}


class LogViewer(RichLog):
    """A scrollable log panel driven by pipeline LogEvent messages."""

    DEFAULT_CSS = """
    LogViewer {
        border: round $primary;
        height: 1fr;
        min-height: 10;
        padding: 0 1;
    }
    LogViewer:focus {
        border: round $accent;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, highlight=True, markup=True, **kwargs)

    def on_log_event(self, event: LogEvent) -> None:
        event.stop()
        style = _LEVEL_STYLES.get(event.level, "white")
        self.write(f"[{style}][{event.stage}] {event.message}[/{style}]")
