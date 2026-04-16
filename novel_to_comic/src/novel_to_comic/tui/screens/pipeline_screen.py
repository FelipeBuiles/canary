"""Pipeline execution screen — run stages with live progress and logs."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label
from textual.worker import Worker, WorkerCancelled

from novel_to_comic.state import (
    STAGE_NAMES,
    StageStatus,
    load_state,
    save_state,
    approve_stage,
)

from ..event_bridge import (
    LogEvent,
    StageBegin,
    StageComplete,
    StageFail,
    StageProgress,
    event_to_message,
)
from ..widgets.stage_progress import StageProgress
from ..widgets.log_viewer import LogViewer
from ..widgets.cost_display import CostDisplay

# Stage module import mapping
_STAGE_MODULES = {
    "extract":    "s1_extract",
    "index":      "s2_index",
    "screenplay": "s3_screenplay",
    "panels":     "s4_panels",
    "prompts":    "s5_prompts",
    "generate":   "s6_generate",
    "assemble":   "s7_assemble",
}


class PipelineScreen(Screen):
    """Run pipeline stages with live progress display."""

    DEFAULT_CSS = """
    PipelineScreen {
        layout: vertical;
    }
    #pipeline-content {
        padding: 1 2;
        height: 1fr;
    }
    """

    def __init__(self, stage: str | None = None) -> None:
        super().__init__()
        self._stage = stage  # None = run all pending

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="pipeline-content"):
            mode = f"Run: {self._stage}" if self._stage else "Run All"
            yield Label(f"[bold]{mode}[/bold]", id="pipeline-header")
            yield StageProgress(id="stage-progress")
            yield LogViewer(id="log-viewer")
            yield CostDisplay(id="cost-display")

            with Vertical(classes="action-row"):
                yield Button("Stop", variant="error", id="stop-btn")
                yield Button("Back to Dashboard", variant="default", id="back-btn")

        yield Footer()

    def on_mount(self) -> None:
        self._start_pipeline()

    def _make_event_callback(self):
        """Create an on_event callback that bridges to Textual messages."""
        screen = self

        def callback(event_dict):
            msg = event_to_message(event_dict)
            if msg:
                screen.post_message(msg)

        return callback

    def _start_pipeline(self) -> None:
        app = self.app
        if not app.config or not app.state or not app.project_dir:
            return

        on_event = self._make_event_callback()
        self._worker = self.run_worker(
            self._run_pipeline(app.config, app.project_dir, app.state, on_event),
            name="pipeline",
            thread=False,
            exclusive=True,
        )

    async def _run_pipeline(self, config, project_dir, state, on_event):
        """Execute pipeline stages."""
        from novel_to_comic.stages import (
            s1_extract, s2_index, s3_screenplay,
            s4_panels, s5_prompts, s6_generate, s7_assemble,
        )

        modules = {
            "extract": s1_extract,
            "index": s2_index,
            "screenplay": s3_screenplay,
            "panels": s4_panels,
            "prompts": s5_prompts,
            "generate": s6_generate,
            "assemble": s7_assemble,
        }

        if self._stage:
            # Run single stage
            stages_to_run = [self._stage]
        else:
            # Run all pending stages
            stages_to_run = []
            for name in STAGE_NAMES:
                s = state.stages[name]
                if s.status == StageStatus.COMPLETE:
                    continue
                if s.status == StageStatus.AWAITING_REVIEW:
                    break  # Stop at checkpoint
                stages_to_run.append(name)

        for stage_name in stages_to_run:
            mod = modules.get(stage_name)
            if mod is None:
                continue

            try:
                # Each stage has different run() signatures
                if stage_name == "extract":
                    await mod.run(config, project_dir, state, on_event=on_event)
                elif stage_name == "index":
                    await mod.run(config, project_dir, state, on_event=on_event)
                elif stage_name in ("screenplay", "panels", "prompts"):
                    await mod.run(config, project_dir, state, scene_ids=None, on_event=on_event)
                elif stage_name == "generate":
                    await mod.run(config, project_dir, state, scene_ids=None, retry_failed=False, on_event=on_event)
                elif stage_name == "assemble":
                    await mod.run(config, project_dir, state, formats=None, rebuild=True, on_event=on_event)
            except Exception as e:
                on_event({"type": "log", "stage": stage_name, "level": "error", "message": str(e)})
                on_event({"type": "stage_fail", "stage": stage_name, "message": str(e)})
                return

            # Reload state after each stage
            try:
                fresh = load_state(project_dir)
                # Update the app's state reference
                self.app.state = fresh
                state = fresh
            except Exception:
                pass

            # Check if we hit a checkpoint
            if state.stages[stage_name].status == StageStatus.AWAITING_REVIEW:
                from .approval_screen import ApprovalScreen
                self.app.push_screen(ApprovalScreen(stage_name))
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop-btn":
            if hasattr(self, "_worker") and self._worker:
                self._worker.cancel()
            self.app.notify("Pipeline stopped.", severity="warning")
        elif event.button.id == "back-btn":
            self.app.pop_screen()

    def on_worker_cancelled(self, event: Worker.Cancelled) -> None:
        pass

    def on_stage_complete(self, event: StageComplete) -> None:
        """Handle stage completion — update cost display."""
        event.stop()
        if self.app.state:
            self.query_one(CostDisplay).update_cost(self.app.state.total_cost_usd)

    def on_stage_progress(self, event: StageProgress) -> None:
        """Update cost on progress."""
        event.stop()
        if self.app.state:
            try:
                fresh = load_state(self.app.project_dir)
                self.app.state = fresh
                self.query_one(CostDisplay).update_cost(fresh.total_cost_usd)
            except Exception:
                pass
