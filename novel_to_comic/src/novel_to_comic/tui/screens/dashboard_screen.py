"""Pipeline dashboard — status table, action buttons, review banners."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static

from novel_to_comic.state import (
    STAGE_NAMES,
    StageStatus,
    load_state,
    save_state,
    approve_stage,
)

from ..widgets.stage_table import StageTable
from ..widgets.cost_display import CostDisplay


class DashboardScreen(Screen):
    """Main project dashboard showing stage status and actions."""

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #dash-content {
        padding: 1 2;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="dash-content"):
            yield Label("", id="dash-title", classes="screen-title")
            yield StageTable(id="stage-table")
            yield CostDisplay(id="cost-display")
            yield Label("", id="review-banner")

            yield Label("")
            with Horizontal(classes="action-row"):
                yield Button("Run All", variant="primary", id="run-all-btn", classes="action-btn")
                yield Button("Run Stage...", variant="default", id="run-stage-btn", classes="action-btn")
                yield Button("Style", variant="default", id="style-btn", classes="action-btn")
                yield Button("Config", variant="default", id="config-btn", classes="action-btn")
                yield Button("Gallery", variant="default", id="gallery-btn", classes="action-btn")
                yield Button("Export", variant="default", id="export-btn", classes="action-btn")
                yield Button("Regen", variant="default", id="regen-btn", classes="action-btn")
                yield Button("Switch Project", variant="default", id="switch-btn", classes="action-btn")

        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def on_screen_resume(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        """Reload state and refresh all widgets."""
        app = self.app
        if not app.project_dir or not app.state:
            return
        # Reload state from disk (may have changed)
        try:
            app.state = load_state(app.project_dir)
        except Exception:
            pass

        state = app.state
        self.query_one("#dash-title", Label).update(
            f"Project: [bold]{state.project_name}[/bold]  "
            f"[dim]{app.project_dir}[/dim]"
        )
        self.query_one(StageTable).update(state)
        self.query_one(CostDisplay).update_cost(state.total_cost_usd)

        # Review banner
        awaiting = [
            n for n in STAGE_NAMES
            if state.stages[n].status == StageStatus.AWAITING_REVIEW
        ]
        banner = self.query_one("#review-banner", Label)
        if awaiting:
            names = ", ".join(awaiting)
            banner.update(
                f"[bold yellow]◈ Checkpoint awaiting review: {names}[/bold yellow]  "
                f"— press [bold]A[/bold] to approve"
            )
            banner.visible = True
        else:
            banner.visible = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "run-all-btn":
            from .pipeline_screen import PipelineScreen
            self.app.push_screen(PipelineScreen())
        elif btn_id == "run-stage-btn":
            self.app.push_screen(StageSelectModal())
        elif btn_id == "style-btn":
            from .style_screen import StyleScreen
            self.app.push_screen(StyleScreen())
        elif btn_id == "config-btn":
            from .config_screen import ConfigScreen
            self.app.push_screen(ConfigScreen())
        elif btn_id == "gallery-btn":
            from .gallery_screen import GalleryScreen
            self.app.push_screen(GalleryScreen())
        elif btn_id == "export-btn":
            from .export_screen import ExportScreen
            self.app.push_screen(ExportScreen())
        elif btn_id == "regen-btn":
            from .regen_screen import RegenScreen
            self.app.push_screen(RegenScreen())
        elif btn_id == "switch-btn":
            # Pop back to project screen
            while len(self.app.screen_stack) > 1:
                self.app.pop_screen()

    def key_a(self) -> None:
        """Approve the first awaiting checkpoint."""
        app = self.app
        if not app.state or not app.project_dir:
            return
        awaiting = [
            n for n in STAGE_NAMES
            if app.state.stages[n].status == StageStatus.AWAITING_REVIEW
        ]
        if awaiting:
            stage_name = awaiting[0]
            try:
                approve_stage(app.state, stage_name)
                save_state(app.state, app.project_dir)
                self.app.notify(f"Approved: {stage_name}", severity="information")
            except ValueError as e:
                self.app.notify(str(e), severity="error")
            self._refresh()


class StageSelectModal(Screen):
    """Modal for selecting a single stage to run."""

    DEFAULT_CSS = """
    StageSelectModal {
        align: center middle;
    }
    StageSelectModal > Vertical {
        width: 40;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Run Stage", classes="screen-title")
            for name in STAGE_NAMES:
                yield Button(
                    name, variant="default", id=f"stage-{name}", classes="action-btn"
                )
            yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
            return

        if event.button.id and event.button.id.startswith("stage-"):
            stage_name = event.button.id.removeprefix("stage-")
            self.app.pop_screen()
            from .pipeline_screen import PipelineScreen
            self.app.push_screen(PipelineScreen(stage=stage_name))
