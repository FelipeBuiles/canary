"""Checkpoint approval screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static

from novel_to_comic.state import (
    STAGE_NAMES,
    StageStatus,
    approve_stage,
    load_state,
    save_state,
)


class ApprovalScreen(Screen):
    """Review and approve a checkpoint stage."""

    DEFAULT_CSS = """
    ApprovalScreen {
        layout: vertical;
    }
    #approval-content {
        padding: 1 2;
        height: 1fr;
    }
    """

    def __init__(self, stage: str) -> None:
        super().__init__()
        self._stage = stage

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="approval-content"):
            yield Label(
                f"[bold yellow]Checkpoint: {self._stage}[/bold yellow]",
                classes="screen-title",
            )
            yield Static(id="approval-details")
            yield Label("")
            with Horizontal(classes="action-row"):
                yield Button(
                    "Approve & Continue", variant="success", id="approve-continue-btn"
                )
                yield Button(
                    "Approve Only", variant="primary", id="approve-only-btn"
                )
                yield Button(
                    "Regenerate Panels", variant="warning", id="regen-btn"
                )
                yield Button(
                    "Back to Dashboard", variant="default", id="back-btn"
                )

        yield Footer()

    def on_mount(self) -> None:
        self._load_details()

    def _load_details(self) -> None:
        """Load and display details about the checkpoint stage."""
        app = self.app
        if not app.project_dir or not app.state:
            return

        state = app.state
        details = self.query_one("#approval-details", Static)
        stage_state = state.stages[self._stage]
        lines = [
            f"Stage: [bold]{self._stage}[/bold]",
            f"Status: [yellow]{stage_state.status.value}[/yellow]",
            f"Items processed: {stage_state.items_done}/{stage_state.items_total}",
            f"Cost: ${stage_state.cost_usd:.3f}",
            "",
        ]

        # Stage-specific details
        if self._stage == "extract":
            lines.append("[bold]Extraction output:[/bold]")
            bible_path = app.project_dir / "story_bible.json"
            if bible_path.exists():
                try:
                    import json
                    bible = json.loads(bible_path.read_text())
                    lines.append(f"  Characters: {len(bible.get('characters', []))}")
                    lines.append(f"  Locations: {len(bible.get('locations', []))}")
                    lines.append(f"  Scenes: {len(bible.get('scenes', []))}")
                except Exception:
                    lines.append("  [dim]Could not read story_bible.json[/dim]")
            else:
                lines.append("  [dim]story_bible.json not found[/dim]")

        elif self._stage == "index":
            lines.append("[bold]Index output:[/bold]")
            refs_dir = app.project_dir / "refs"
            plates_dir = app.project_dir / "plates"
            char_count = sum(1 for _ in refs_dir.iterdir()) if refs_dir.exists() else 0
            plate_count = sum(1 for f in plates_dir.iterdir() if f.suffix == ".png") if plates_dir.exists() else 0
            lines.append(f"  Character refs: {char_count}")
            lines.append(f"  Location plates: {plate_count}")

        elif self._stage == "generate":
            lines.append("[bold]Generated images:[/bold]")
            images_dir = app.project_dir / "images"
            if images_dir.exists():
                count = sum(1 for _ in images_dir.rglob("*.png"))
                lines.append(f"  Panel images: {count}")
                lines.append("")
                lines.append("[dim]Use Gallery to review generated images.[/dim]")

        details.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.app
        if not app.state or not app.project_dir:
            return

        if event.button.id in ("approve-continue-btn", "approve-only-btn"):
            try:
                approve_stage(app.state, self._stage)
                save_state(app.state, app.project_dir)
                self.app.notify(f"Approved: {self._stage}", severity="information")
            except ValueError as e:
                self.app.notify(str(e), severity="error")
                return

            # Pop approval screen
            self.app.pop_screen()

            if event.button.id == "approve-continue-btn":
                # Pop back to dashboard and launch pipeline
                self.app.pop_screen()
                from .pipeline_screen import PipelineScreen
                self.app.push_screen(PipelineScreen())
            # "approve only" just returns to dashboard

        elif event.button.id == "regen-btn":
            from .regen_screen import RegenScreen
            self.app.push_screen(RegenScreen())

        elif event.button.id == "back-btn":
            self.app.pop_screen()
