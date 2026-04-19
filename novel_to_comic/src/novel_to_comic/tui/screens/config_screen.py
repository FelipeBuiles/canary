"""Configuration viewing and editing screen."""

from __future__ import annotations

import os
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

from novel_to_comic.config import Config, save_config, _ENV_KEYS

_API_KEY_ENV_KEYS = {
    name: field
    for name, field in _ENV_KEYS.items()
    if name.endswith("API_KEY")
}


class ConfigScreen(Screen):
    """View and edit pipeline configuration."""

    DEFAULT_CSS = """
    ConfigScreen {
        layout: vertical;
    }
    #config-content {
        padding: 1 2;
        height: 1fr;
    }
    #config-content Input {
        margin: 0 0 1 0;
    }
    .config-section {
        margin: 1 0;
        padding: 0 1;
        border: round $primary-darken-2;
    }
    """

    # Fields that can be edited (non-sensitive, non-API-key)
    _EDITABLE_FIELDS = [
        ("extraction_model", "Extraction model"),
        ("screenplay_model", "Screenplay model"),
        ("panel_model", "Panel model"),
        ("prompt_model", "Prompt model"),
        ("embedding_model", "Embedding model"),
        ("image_model", "Image model"),
        ("fallback_image_model", "Fallback image model"),
        ("max_panels_per_scene", "Max panels/scene"),
        ("max_panels_per_page", "Max panels/page"),
        ("parallel_batch_size", "Parallel batch size"),
        ("max_concurrent_requests", "Max concurrent requests"),
        ("cost_limit_usd", "Cost limit (USD)"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="config-content"):
            yield Label("Configuration", classes="screen-title")
            yield Static(id="api-keys-section")
            yield Label("")

            yield Label("[bold]Model & Pipeline Settings[/bold]")
            for field_name, label in self._EDITABLE_FIELDS:
                with Horizontal():
                    yield Label(f"{label}:", classes="config-label")
                    yield Input(
                        value="",
                        placeholder=f"field_name",
                        id=f"cfg-{field_name}",
                    )

            yield Label("")
            with Horizontal(classes="action-row"):
                yield Button("Save", variant="success", id="save-btn")
                yield Button("Back", variant="default", id="back-btn")

        yield Footer()

    def on_mount(self) -> None:
        self._load_config()

    def _load_config(self) -> None:
        app = self.app
        if not app.config:
            return

        config = app.config

        # Google auth / API keys section (read-only)
        lines = ["[bold]Google Auth[/bold]\n"]
        lines.append(f"  GOOGLE_GENAI_USE_VERTEXAI: {str(config.google_use_vertex_ai).lower()}")
        lines.append(f"  GOOGLE_CLOUD_PROJECT: {config.google_cloud_project or '[red]NOT SET[/red]'}")
        lines.append(f"  GOOGLE_CLOUD_LOCATION: {config.google_cloud_location or 'global'}")
        lines.append("\n[bold]API Keys[/bold]")
        for env_name, field_name in _API_KEY_ENV_KEYS.items():
            val = getattr(config, field_name, "")
            if not val:
                masked = "[red]NOT SET[/red]"
            elif len(val) > 12:
                masked = f"[green]{val[:8]}...{val[-4:]}[/green]"
            else:
                masked = "[green]set[/green]"

            in_shell = bool(os.environ.get(env_name, "").strip())
            source = "shell env" if in_shell else (".env" if val else "not found")
            lines.append(f"  {env_name}: {masked}  [dim]({source})[/dim]")

        self.query_one("#api-keys-section", Static).update("\n".join(lines))

        # Editable fields
        for field_name, _label in self._EDITABLE_FIELDS:
            val = getattr(config, field_name, "")
            input_el = self.query_one(f"#cfg-{field_name}", Input)
            input_el.value = str(val) if val is not None else ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
            return

        if event.button.id == "save-btn":
            app = self.app
            if not app.config or not app.project_dir:
                return

            config = app.config
            for field_name, _label in self._EDITABLE_FIELDS:
                input_el = self.query_one(f"#cfg-{field_name}", Input)
                raw = input_el.value.strip()

                # Type coercion
                field_info = Config.model_fields.get(field_name)
                if field_info is None:
                    continue
                ann = field_info.annotation
                if ann is float or ann is float | None:
                    raw = float(raw) if raw else None
                elif ann is int:
                    raw = int(raw) if raw else 0

                setattr(config, field_name, raw)

            save_config(config, app.project_dir)
            self.app.notify("Configuration saved.", severity="information")
            self.app.pop_screen()
