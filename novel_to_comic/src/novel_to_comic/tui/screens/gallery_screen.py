"""Gallery screen — browse generated panel images by scene."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static


class GalleryScreen(Screen):
    """Browse generated panel images organized by scene."""

    DEFAULT_CSS = """
    GalleryScreen {
        layout: vertical;
    }
    #gallery-content {
        padding: 1 2;
        height: 1fr;
    }
    .scene-section {
        margin: 1 0;
    }
    .panel-item {
        margin: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._scenes: dict[str, list[Path]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="gallery-content"):
            yield Label("Gallery — Generated Panels", classes="screen-title")
            yield Static(id="gallery-list")
            yield Label("")
            with Horizontal(classes="action-row"):
                yield Button("Refresh", variant="default", id="refresh-btn")
                yield Button("Back", variant="default", id="back-btn")

        yield Footer()

    def on_mount(self) -> None:
        self._scan_images()

    def on_screen_resume(self) -> None:
        self._scan_images()

    def _scan_images(self) -> None:
        app = self.app
        if not app.project_dir:
            return

        images_dir = app.project_dir / "images"
        self._scenes = {}

        if images_dir.exists():
            for scene_dir in sorted(images_dir.iterdir()):
                if scene_dir.is_dir():
                    panels = sorted(scene_dir.glob("panel_*.png"))
                    if panels:
                        self._scenes[scene_dir.name] = panels

        # Render
        list_el = self.query_one("#gallery-list", Static)
        if not self._scenes:
            list_el.update("[dim]No generated images found. Run the generate stage first.[/dim]")
            return

        lines = []
        for scene_id, panels in self._scenes.items():
            lines.append(f"[bold]{scene_id}[/bold]  ({len(panels)} panels)")
            for p in panels:
                lines.append(f"  [cyan]{p.name}[/cyan]  [dim]{p.stat().st_size // 1024}KB[/dim]")
            lines.append("")

        list_el.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "refresh-btn":
            self._scan_images()
