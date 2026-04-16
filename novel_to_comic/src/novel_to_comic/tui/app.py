"""CanaryApp — root Textual application for the novel-to-comic TUI."""

from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from novel_to_comic.config import Config, load_config
from novel_to_comic.state import PipelineState, load_state

from .console_redirect import install, uninstall
from .screens.project_screen import ProjectScreen
from .screens.dashboard_screen import DashboardScreen


class CanaryApp(App):
    """A Textual TUI for the novel-to-comic pipeline."""

    TITLE = "Canary"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "go_back", "Back", show=False),
    ]

    def __init__(self, *, project_dir: Path | None = None) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.config: Config | None = None
        self.state: PipelineState | None = None
        self._original_print = None

    def on_mount(self) -> None:
        """Silence Rich console and push the initial screen."""
        self._original_print = install()
        if self.project_dir:
            self.load_project(self.project_dir)
        else:
            self.push_screen(ProjectScreen())

    def on_unmount(self) -> None:
        """Restore Rich console."""
        if self._original_print:
            uninstall(self._original_print)

    def load_project(self, project_dir: Path) -> None:
        """Load a project and show its dashboard."""
        project_dir = project_dir.resolve()
        try:
            self.config, _ = load_config(project_dir)
            self.state = load_state(project_dir)
        except FileNotFoundError as e:
            self.notify(str(e), severity="error")
            return
        self.project_dir = project_dir
        self.push_screen(DashboardScreen())

    def action_go_back(self) -> None:
        """Pop the current screen (Escape key)."""
        if len(self.screen_stack) > 1:
            self.pop_screen()


def main() -> None:
    """Entry point for the ``pipeline`` command."""
    # --cli flag: delegate to Click CLI
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from novel_to_comic.cli import cli
        cli()
        return

    # If a project directory is passed as a positional arg, use it
    project_dir: Path | None = None
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        candidate = Path(args[0])
        if candidate.is_dir() and (candidate / "state.json").exists():
            project_dir = candidate
            sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != args[0]]

    app = CanaryApp(project_dir=project_dir)
    app.run()


if __name__ == "__main__":
    main()
