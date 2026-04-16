"""Progress bar widget bound to stage events."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label, ProgressBar

from ..event_bridge import StageBegin, StageProgress, StageComplete


class StageProgress(Widget):
    """A progress bar that tracks stage events."""

    DEFAULT_CSS = """
    StageProgress {
        height: 3;
        margin: 1 0;
    }
    StageProgress ProgressBar {
        bar-height: 1;
    }
    StageProgress #stage-label {
        width: 100%;
        height: 1;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stage_name = ""

    def compose(self) -> ComposeResult:
        yield Label("", id="stage-label")
        yield ProgressBar(total=100, show_percentage=True, show_eta=False)

    def on_stage_begin(self, event: StageBegin) -> None:
        event.stop()
        self._stage_name = event.stage
        self.query_one("#stage-label", Label).update(
            f"Running: [bold]{event.stage}[/bold]"
        )
        pb = self.query_one(ProgressBar)
        pb.total = event.total or 1
        pb.progress = 0

    def on_stage_progress(self, event: StageProgress) -> None:
        event.stop()
        pb = self.query_one(ProgressBar)
        if pb.total != event.total and event.total > 0:
            pb.total = event.total
        pb.progress = event.done

    def on_stage_complete(self, event: StageComplete) -> None:
        event.stop()
        self.query_one("#stage-label", Label).update(
            f"[green]Complete:[/green] [bold]{event.stage}[/bold] ({event.done}/{event.total})"
        )
        pb = self.query_one(ProgressBar)
        pb.progress = event.total
