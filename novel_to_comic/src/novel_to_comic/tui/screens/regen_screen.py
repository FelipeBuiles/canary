"""Panel regeneration screen."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from ..event_bridge import event_to_message
from ..widgets.stage_progress import StageProgress


class RegenScreen(Screen):
    """Select and regenerate specific panels."""

    DEFAULT_CSS = """
    RegenScreen {
        layout: vertical;
    }
    #regen-content {
        padding: 1 2;
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._scene_id: str | None = None
        self._panels: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="regen-content"):
            yield Label("Regenerate Panels", classes="screen-title")

            yield Label("Scene ID:")
            yield Input(placeholder="scene_001", id="regen-scene")
            yield Label("Panel numbers (space-separated, e.g. 1 3 5):")
            yield Input(placeholder="1 3 5", id="regen-panels")
            yield Checkbox("Skip prompts (keep existing prompt JSON)", value=False, id="cb-skip-prompts")

            yield Label("")
            yield StageProgress(id="regen-progress")
            yield Static(id="regen-status")

            yield Label("")
            with Horizontal(classes="action-row"):
                yield Button("Regenerate", variant="success", id="regen-btn")
                yield Button("Back", variant="default", id="back-btn")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return

        if event.button.id == "regen-btn":
            self._do_regen()

    def _do_regen(self) -> None:
        app = self.app
        if not app.config or not app.project_dir or not app.state:
            return

        scene = self.query_one("#regen-scene", Input).value.strip()
        panels_raw = self.query_one("#regen-panels", Input).value.strip()
        skip_prompts = self.query_one("#cb-skip-prompts", Checkbox).value

        if not scene:
            self.app.notify("Enter a scene ID.", severity="error")
            return
        if not panels_raw:
            self.app.notify("Enter panel numbers.", severity="error")
            return

        try:
            panel_numbers = [int(x) for x in panels_raw.replace(",", " ").split()]
        except ValueError:
            self.app.notify("Invalid panel numbers.", severity="error")
            return

        # Clear cached files
        cleared: list[str] = []
        for num in panel_numbers:
            tag = f"panel_{num:03d}"
            if not skip_prompts:
                p = app.project_dir / "prompts" / scene / f"{tag}.json"
                if p.exists():
                    p.unlink()
                    cleared.append(f"prompts/{scene}/{tag}.json")
            img = app.project_dir / "images" / scene / f"{tag}.png"
            if img.exists():
                img.unlink()
                cleared.append(f"images/{scene}/{tag}.png")

        status = self.query_one("#regen-status", Static)
        if cleared:
            status.update(f"[dim]Cleared: {', '.join(cleared)}[/dim]")
        else:
            status.update("[yellow]No cached files found.[/yellow]")

        screen = self

        def on_event(event_dict):
            msg = event_to_message(event_dict)
            if msg:
                screen.post_message(msg)

        self.run_worker(
            self._run_regen(
                app.config, app.project_dir, app.state,
                scene, skip_prompts, on_event,
            ),
            thread=False,
            name="regen",
        )

    async def _run_regen(self, config, project_dir, state, scene, skip_prompts, on_event):
        from novel_to_comic.stages import s5_prompts, s6_generate

        status = self.query_one("#regen-status", Static)
        try:
            if not skip_prompts:
                status.update(f"[bold]Regenerating prompts for {scene}...[/bold]")
                await s5_prompts.run(config, project_dir, state, scene_ids=[scene], on_event=on_event)

            status.update(f"[bold]Regenerating images for {scene}...[/bold]")
            await s6_generate.run(config, project_dir, state, scene_ids=[scene], on_event=on_event)

            status.update("[green]Done. Run Export to rebuild comic pages.[/green]")
            self.app.notify("Regeneration complete.", severity="information")
        except Exception as e:
            status.update(f"[red]Failed: {e}[/red]")
            self.app.notify(f"Regeneration failed: {e}", severity="error")
