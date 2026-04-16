"""Project discovery and initialization screen."""

from __future__ import annotations

import shutil
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from novel_to_comic.config import Config, save_config
from novel_to_comic.state import create_initial_state, save_state


class ProjectScreen(Screen):
    """Project discovery, selection, and initialization."""

    DEFAULT_CSS = """
    ProjectScreen {
        layout: vertical;
    }
    #project-content {
        padding: 1 2;
        height: 1fr;
    }
    .project-item {
        padding: 0 1;
        height: 1;
    }
    .project-item:hover {
        background: $primary-darken-2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._projects: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="project-content"):
            yield Label("Canary — Novel to Comic", classes="screen-title")
            yield Label("Select a project or create a new one:")

            yield Label("\n[bold]Recent Projects[/bold]")
            yield Static(id="project-list")
            yield Label("")

            with Horizontal():
                yield Button("Open Directory", variant="primary", id="open-dir-btn")
                yield Button("New Project", variant="success", id="new-project-btn")

        yield Footer()

    def on_mount(self) -> None:
        self._scan_for_projects()

    def _scan_for_projects(self) -> None:
        """Look for projects in cwd and common locations."""
        self._projects = []
        search_dirs = [Path.cwd()]

        # Add ~/Projects and ~/projects if they exist
        home = Path.home()
        for candidate in [home / "Projects", home / "projects"]:
            if candidate.is_dir():
                search_dirs.append(candidate)

        for search_dir in search_dirs:
            if search_dir.is_dir():
                for child in sorted(search_dir.iterdir()):
                    if child.is_dir() and (child / "state.json").exists():
                        if child not in self._projects:
                            self._projects.append(child)

        # Also check cwd itself
        if (Path.cwd() / "state.json").exists() and Path.cwd() not in self._projects:
            self._projects.insert(0, Path.cwd())

        # Render list
        list_el = self.query_one("#project-list", Static)
        if not self._projects:
            list_el.update("[dim]No projects found in current directory.[/dim]")
        else:
            lines = []
            for i, p in enumerate(self._projects):
                try:
                    from novel_to_comic.state import load_state
                    state = load_state(p)
                    stage_status = "complete"
                    for name in ["extract", "index", "screenplay", "panels", "prompts", "generate", "assemble"]:
                        s = state.stages[name]
                        if s.status.value not in ("complete", "pending"):
                            stage_status = s.status.value
                            break
                    lines.append(
                        f"  {i + 1}. [bold]{state.project_name}[/bold] "
                        f"[dim]{p}[/dim]  [{_status_color(stage_status)}]{stage_status}[/{_status_color(stage_status)}]"
                    )
                except Exception:
                    lines.append(f"  {i + 1}. [dim]{p.name}[/dim] {p}")
            list_el.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-project-btn":
            self.app.push_screen(NewProjectModal())
        elif event.button.id == "open-dir-btn":
            self.app.push_screen(OpenDirModal())

    def on_screen_resume(self) -> None:
        """Re-scan when returning to this screen (e.g., after creating a project)."""
        self._scan_for_projects()


def _status_color(status: str) -> str:
    return {
        "complete": "green",
        "running": "blue",
        "awaiting_review": "yellow",
        "failed": "red",
    }.get(status, "dim")


class NewProjectModal(Screen):
    """Modal for creating a new project."""

    DEFAULT_CSS = """
    NewProjectModal {
        align: center middle;
    }
    NewProjectModal > Vertical {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Create New Project", classes="screen-title")
            yield Label("Path to novel (.txt or .epub):")
            yield Input(placeholder="/path/to/novel.epub", id="novel-path")
            yield Label("Project name (optional):")
            yield Input(placeholder="My Novel", id="project-name")
            yield Label("")
            with Horizontal():
                yield Button("Create", variant="success", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
            return

        if event.button.id == "create-btn":
            novel_path = self.query_one("#novel-path", Input).value.strip()
            project_name = self.query_one("#project-name", Input).value.strip()

            if not novel_path:
                self.app.notify("Please enter a novel path", severity="error")
                return

            src = Path(novel_path).resolve()
            if not src.exists():
                self.app.notify(f"File not found: {src}", severity="error")
                return

            name = project_name or src.stem
            project_dir = Path.cwd()

            if (project_dir / "state.json").exists():
                self.app.notify(
                    "A project already exists in this directory.",
                    severity="error",
                )
                return

            # Create project structure
            for subdir in [
                "input", "scenes", "refs", "plates", "screenplays",
                "panels", "prompts", "images", "assembly", "exports",
            ]:
                (project_dir / subdir).mkdir(exist_ok=True)

            dst = project_dir / "input" / src.name
            shutil.copy2(src, dst)

            config = Config()
            save_config(config, project_dir)
            state = create_initial_state(name, str(dst))
            save_state(state, project_dir)

            self.app.pop_screen()  # close modal
            self.app.load_project(project_dir)


class OpenDirModal(Screen):
    """Modal for opening an existing project directory."""

    DEFAULT_CSS = """
    OpenDirModal {
        align: center middle;
    }
    OpenDirModal > Vertical {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Open Project Directory", classes="screen-title")
            yield Label("Path to project directory:")
            yield Input(placeholder=".", id="dir-path")
            yield Label("")
            with Horizontal():
                yield Button("Open", variant="primary", id="open-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
            return

        if event.button.id == "open-btn":
            dir_path = self.query_one("#dir-path", Input).value.strip() or "."
            p = Path(dir_path).resolve()
            if not p.is_dir():
                self.app.notify(f"Not a directory: {p}", severity="error")
                return
            if not (p / "state.json").exists():
                self.app.notify(
                    f"No state.json found in {p}",
                    severity="error",
                )
                return
            self.app.pop_screen()  # close modal
            self.app.load_project(p)
