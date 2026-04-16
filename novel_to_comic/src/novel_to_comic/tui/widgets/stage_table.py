"""Stage status table widget — mirrors CLI ``pipeline status`` output."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from novel_to_comic.state import STAGE_NAMES, PipelineState, StageStatus

_STATUS_STYLES = {
    StageStatus.PENDING: "dim",
    StageStatus.RUNNING: "bold blue",
    StageStatus.AWAITING_REVIEW: "bold yellow",
    StageStatus.COMPLETE: "green",
    StageStatus.FAILED: "bold red",
}

_STATUS_ICONS = {
    StageStatus.PENDING: "○",
    StageStatus.RUNNING: "●",
    StageStatus.AWAITING_REVIEW: "◈",
    StageStatus.COMPLETE: "✓",
    StageStatus.FAILED: "✗",
}


class StageTable(Widget):
    """Display pipeline stage status as a table."""

    DEFAULT_CSS = """
    StageTable {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._state: PipelineState | None = None

    def update(self, state: PipelineState) -> None:
        """Refresh the table from current pipeline state."""
        self._state = state
        self.refresh(layout=True)

    def compose(self) -> ComposeResult:
        if self._state is None:
            return
        with Vertical(classes="stage-table"):
            # Header
            yield Static(
                f"  {'Stage':<14} {'Status':<18} {'Progress':<12} {'Cost':<10} {'Error'}",
                classes="stage-row dim",
            )
            for name in STAGE_NAMES:
                s = self._state.stages[name]
                style = _STATUS_STYLES.get(s.status, "")
                icon = _STATUS_ICONS.get(s.status, " ")

                progress = ""
                if s.items_total > 0:
                    progress = f"{s.items_done}/{s.items_total}"
                    if s.items_failed:
                        progress += f" ({len(s.items_failed)} failed)"

                cost = f"${s.cost_usd:.3f}" if s.cost_usd > 0 else ""
                error = s.error[:40] if s.error else ""

                yield Static(
                    f"  {icon} {name:<12} [{style}]{s.status.value:<18}[/{style}] "
                    f"{progress:<12} {cost:<10} {error}",
                    classes="stage-row",
                )
