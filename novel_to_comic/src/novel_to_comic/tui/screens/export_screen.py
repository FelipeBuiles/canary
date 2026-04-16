"""Export screen — render comic pages to PDF/CBZ."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Label, Static

from ..event_bridge import event_to_message
from ..widgets.stage_progress import StageProgress
from ..widgets.cost_display import CostDisplay


class ExportScreen(Screen):
    """Export comic pages to PDF and/or CBZ."""

    DEFAULT_CSS = """
    ExportScreen {
        layout: vertical;
    }
    #export-content {
        padding: 1 2;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="export-content"):
            yield Label("Export Comic", classes="screen-title")

            yield Checkbox("PDF", value=True, id="cb-pdf")
            yield Checkbox("CBZ", value=True, id="cb-cbz")

            yield Label("")
            yield Checkbox("Rebuild page JSON from panel data", value=False, id="cb-rebuild")

            yield Label("")
            yield StageProgress(id="export-progress")
            yield Static(id="export-status")
            yield CostDisplay(id="export-cost")

            yield Label("")
            with Horizontal(classes="action-row"):
                yield Button("Export", variant="success", id="export-btn")
                yield Button("Back", variant="default", id="back-btn")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return

        if event.button.id == "export-btn":
            self._do_export()

    def _do_export(self) -> None:
        app = self.app
        if not app.config or not app.project_dir or not app.state:
            return

        formats = []
        if self.query_one("#cb-pdf", Checkbox).value:
            formats.append("pdf")
        if self.query_one("#cb-cbz", Checkbox).value:
            formats.append("cbz")

        if not formats:
            self.app.notify("Select at least one format.", severity="error")
            return

        rebuild = self.query_one("#cb-rebuild", Checkbox).value
        status = self.query_one("#export-status", Static)
        status.update("[bold]Exporting...[/bold]")

        # Build event callback
        screen = self

        def on_event(event_dict):
            msg = event_to_message(event_dict)
            if msg:
                screen.post_message(msg)

        self.run_worker(
            self._run_export(app.config, app.project_dir, app.state, formats, rebuild, on_event),
            thread=False,
            name="export",
        )

    async def _run_export(self, config, project_dir, state, formats, rebuild, on_event):
        from novel_to_comic.stages import s7_assemble

        try:
            await s7_assemble.run(config, project_dir, state, formats=formats, rebuild=rebuild, on_event=on_event)
            self.query_one("#export-status", Static).update("[green]Export complete![/green]")
            self.app.notify("Export complete.", severity="information")
        except Exception as e:
            self.query_one("#export-status", Static).update(f"[red]Export failed: {e}[/red]")
            self.app.notify(f"Export failed: {e}", severity="error")
