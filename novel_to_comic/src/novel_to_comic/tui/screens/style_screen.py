"""Style suggestions and selection screen."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Static,
)
from textual.worker import Worker

from novel_to_comic.config import Config, save_config


_STYLE_SUGGESTIONS_FILE = "samples/style_suggestions.json"


class StyleScreen(Screen):
    """Generate, preview, and select visual style templates."""

    DEFAULT_CSS = """
    StyleScreen {
        layout: vertical;
    }
    #style-content {
        padding: 1 2;
        height: 1fr;
    }
    .style-card {
        border: round $primary-darken-2;
        margin: 1 0;
        padding: 0 1;
        height: auto;
    }
    .style-card.active {
        border: round $success;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._suggestions: list[dict] = []
        self._active_idx: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="style-content"):
            yield Label("Visual Style", classes="screen-title")
            yield Static(id="style-cards")
            yield Label("")

            with Horizontal(classes="action-row"):
                yield Button("Refresh Suggestions", variant="default", id="refresh-btn")
                yield Button("Generate All Samples", variant="primary", id="gen-all-btn")
                yield Button("Back", variant="default", id="back-btn")

            yield Label("")
            yield Label("Select style [1-N] or 0 for custom:")
            yield Input(placeholder="0", id="style-choice")
            with Horizontal(classes="action-row"):
                yield Button("Apply", variant="success", id="apply-btn")

        yield Footer()

    def on_mount(self) -> None:
        self._load_or_generate(refresh=False)

    def _load_or_generate(self, refresh: bool = False) -> None:
        app = self.app
        if not app.project_dir or not app.config:
            return

        bible_path = app.project_dir / "story_bible.json"
        if not bible_path.exists():
            self.query_one("#style-cards", Static).update(
                "[yellow]story_bible.json not found — run extract first.[/yellow]"
            )
            return

        # Try loading saved suggestions
        suggestions_path = app.project_dir / _STYLE_SUGGESTIONS_FILE
        if not refresh and suggestions_path.exists():
            try:
                data = json.loads(suggestions_path.read_text())
                self._suggestions = data.get("suggestions", []) if isinstance(data, dict) else data
            except Exception:
                self._suggestions = []
        elif refresh or not self._suggestions:
            self._suggestions = []

        if not self._suggestions:
            self.run_worker(self._generate_suggestions(), thread=False, name="gen-suggestions")
        else:
            self._render_cards()

    def _find_active(self) -> int | None:
        """Find which suggestion matches the current config."""
        app = self.app
        if not app.config:
            return None
        for i, s in enumerate(self._suggestions):
            if isinstance(s, dict) and s.get("template", "").strip() == app.config.style_template.strip():
                return i + 1
        return None

    def _render_cards(self) -> None:
        self._active_idx = self._find_active()
        samples_dir = app.project_dir / "samples" if (app := self.app) and app.project_dir else None
        lines = []
        for i, s in enumerate(self._suggestions, 1):
            if not isinstance(s, dict):
                continue
            label = s.get("label", f"Style {i}")
            template = s.get("template", "")
            active_tag = " [green]← active[/green]" if i == self._active_idx else ""
            sample_tag = ""
            if samples_dir and (samples_dir / f"style_{i}.png").exists():
                sample_tag = " [dim](sample exists)[/dim]"

            lines.append(
                f"[bold cyan]{i}. {label}[/bold cyan]{active_tag}{sample_tag}"
            )
            lines.append(f"   {template[:200]}\n")

        if not lines:
            lines.append("[dim]No suggestions loaded yet.[/dim]")

        self.query_one("#style-cards", Static).update("\n".join(lines))

    async def _generate_suggestions(self) -> None:
        """Generate style suggestions via LLM."""
        app = self.app
        if not app.config or not app.project_dir:
            return

        from novel_to_comic.models.story_bible import StoryBible
        bible_path = app.project_dir / "story_bible.json"
        bible = StoryBible.model_validate_json(bible_path.read_text())

        from novel_to_comic.clients import gemini

        system = (
            "You are a visual art director for adapted fiction. Given a story's details, generate 5 "
            "distinct visual style templates for image generation prompts. "
            "Span the full medium spectrum — do NOT default to illustrated or comic styles. "
            "At least one suggestion must be photorealistic or cinematic. "
            "Each is a single paragraph of 40-70 words describing: medium/rendering style, color palette, "
            "lighting, composition, mood. Make each genuinely distinct. Output a JSON array only, no markdown."
        )
        user = (
            f'Story: "{bible.title}" by {bible.author}\n'
            f"Style notes: {bible.style_notes or 'none'}\n"
            f"Genre/tone: {', '.join({s.scene_type for s in bible.scenes})}\n"
            f"Characters: {'; '.join(f'{c.name} ({c.gender}, {c.age_range})' for c in bible.characters[:5])}\n\n"
            f"Generate 5 style options. Output JSON array of 5 objects: "
            f'[{{"label": "Style Name", "template": "40-70 word description"}}, ...]'
        )

        result = await gemini.generate_json(
            config=app.config, model=app.config.screenplay_model,
            system_prompt=system, user_content=user,
        )

        if isinstance(result, list):
            self._suggestions = result
        elif isinstance(result, dict):
            self._suggestions = result.get("styles", [])

        # Save to disk
        path = app.project_dir / _STYLE_SUGGESTIONS_FILE
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({
            "title": bible.title,
            "suggestions": self._suggestions,
        }, indent=2))

        self._render_cards()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "refresh-btn":
            self._load_or_generate(refresh=True)
        elif event.button.id == "gen-all-btn":
            self.run_worker(self._generate_all_samples(), thread=False, name="gen-samples")
        elif event.button.id == "apply-btn":
            self._apply_choice()

    async def _generate_all_samples(self) -> None:
        """Generate sample images for all suggestions."""
        app = self.app
        if not app.config or not app.project_dir or not self._suggestions:
            return

        from novel_to_comic.models.story_bible import StoryBible
        from novel_to_comic.clients import flux

        bible_path = app.project_dir / "story_bible.json"
        bible = StoryBible.model_validate_json(bible_path.read_text())
        samples_dir = app.project_dir / "samples"
        samples_dir.mkdir(exist_ok=True)

        first_char = bible.characters[0] if bible.characters else None
        first_loc = bible.locations[0] if bible.locations else None

        for i, s in enumerate(self._suggestions, 1):
            if not isinstance(s, dict):
                continue
            sample_path = samples_dir / f"style_{i}.png"
            if sample_path.exists():
                continue

            template = s.get("template", app.config.style_template)
            sample_config = app.config.model_copy(update={"style_template": template})

            char_desc = (first_char.visual_anchor or first_char.name)[:200] if first_char else "a mysterious cloaked figure"
            loc_desc = (first_loc.visual_anchor or first_loc.name)[:200] if first_loc else "a dramatic atmospheric setting"

            prompt = (
                f"{template}\n\n"
                f"{char_desc}. Set in: {loc_desc}. "
                f"Medium shot, eye-level camera, dramatic lighting. "
                f"No text. No speech bubbles. No captions. Single panel only."
            )

            try:
                await flux.generate_image(config=sample_config, prompt=prompt, output_path=sample_path)
            except Exception:
                pass

        self._render_cards()
        self.app.notify("Samples generated.", severity="information")

    def _apply_choice(self) -> None:
        app = self.app
        if not app.config or not app.project_dir:
            return

        raw = self.query_one("#style-choice", Input).value.strip()
        if not raw:
            self.app.notify("Keeping current style.", severity="information")
            return

        try:
            choice = int(raw)
        except ValueError:
            self.app.notify("Invalid choice.", severity="error")
            return

        if choice == 0:
            # Custom — prompt for template text
            self.app.notify("Enter custom template in the input field.", severity="information")
            return
        elif 1 <= choice <= len(self._suggestions):
            template = self._suggestions[choice - 1].get("template", "")
            if not template:
                self.app.notify("Empty template.", severity="error")
                return
            app.config.style_template = template
            save_config(app.config, app.project_dir)
            self.app.notify(f"Style {choice} applied.", severity="information")
            self._render_cards()
        else:
            self.app.notify("Invalid choice.", severity="error")
