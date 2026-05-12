"""Click CLI entry point — project initialisation and server launch."""

import shutil
from pathlib import Path

import click
from rich.console import Console

from novel_to_comic.config import (
    Config,
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_QUALITY,
    load_config,
    save_config,
)
from novel_to_comic.state import create_initial_state, save_state

console = Console()

_INIT_IMAGE_MODEL_CHOICES: list[tuple[str, str]] = [
    (GATEWAY_IMAGE_FAST, "Fast image model (Gemini Flash Image)"),
    (GATEWAY_IMAGE_BALANCED, "Balanced image model (Gemini Pro Image)"),
    (GATEWAY_IMAGE_QUALITY, "Quality image model (gpt-image-2)"),
]


def _choose_image_model(default_model: str) -> str:
    """Interactive image model picker for project init."""
    console.print("\n[bold]Select image generation model[/bold]")
    default_idx = 0
    for i, (model_id, label) in enumerate(_INIT_IMAGE_MODEL_CHOICES, 1):
        default_tag = " [green](default)[/green]" if model_id == default_model else ""
        if model_id == default_model:
            default_idx = i
        console.print(f"  [cyan]{i}[/cyan]. {label} — [dim]{model_id}[/dim]{default_tag}")
    console.print("  [cyan]0[/cyan]. Custom model id")

    choice = click.prompt("Image model", default=str(default_idx or 0), show_default=True)
    try:
        idx = int(str(choice).strip())
    except ValueError:
        idx = default_idx or 0

    if idx == 0:
        return click.prompt("Custom image model id", default=default_model, show_default=True).strip()
    if 1 <= idx <= len(_INIT_IMAGE_MODEL_CHOICES):
        return _INIT_IMAGE_MODEL_CHOICES[idx - 1][0]
    return default_model


@click.group()
def cli():
    """Novel-to-Comic pipeline."""
    pass


@cli.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.option("--name", default=None, help="Project name (default: input filename stem)")
@click.option("--image-model", default=None, help="Image model id to set in config.yaml")
def init(input_path: str, name: str | None, image_model: str | None):
    """Initialise the current directory as a comic project.

    INPUT_PATH is the path to your novel file (.txt or .epub).
    All project files are created in the current directory — no subfolder.

    Example (from an empty project directory):
        mkdir monkeypaw && cd monkeypaw
        pipeline init ../themonkeyspaw.txt
    """
    src = Path(input_path).resolve()
    project_name = name or src.stem
    project_dir = Path(".").resolve()

    if (project_dir / "state.json").exists():
        raise click.ClickException(
            f"A project already exists here ({project_dir}).\n"
            f"Delete state.json first, or cd into an empty directory."
        )

    for subdir in ["input", "scenes", "refs", "plates", "adapt", "plan", "storyboard",
                   "direct", "draw", "compose", "exports"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    dst = project_dir / "input" / src.name
    shutil.copy2(src, dst)

    config = Config()
    selected_image_model = (image_model or "").strip() or _choose_image_model(config.image_model)
    config.image_model = selected_image_model
    save_config(config, project_dir)
    state = create_initial_state(project_name, str(dst))
    save_state(state, project_dir)

    (project_dir / ".env.example").write_text(
        "# AI gateway keys — copy to a .env at your repo root (not per-project).\n"
        "# The pipeline walks up from any project dir to find the nearest .env.\n"
        "# Never commit the real .env — add it to your root .gitignore.\n\n"
        "LITELLM_BASE_URL=http://localhost:4000\n"
        "LITELLM_API_KEY=sk-local-canary\n"
        "AI_BILL_FAILED_REQUESTS=provider_usage_only\n"
    )

    console.print(f"[green]Project initialised:[/green] {project_dir}")
    console.print("\nNext steps:")
    console.print("  1. Configure LiteLLM in a [bold].env[/bold] at your repo root")
    console.print("  2. [bold]playwright install chromium[/bold]  ← one-time browser install for assembly")
    console.print("  3. Start the server:  [bold]pipeline serve --projects-dir .[/bold]")
    console.print("  4. Open the web UI and run the pipeline from there")
    console.print(f"\n[dim]Image model set to:[/dim] {config.image_model}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8000, show_default=True, type=int, help="Port number")
@click.option("--projects-dir", default=".", show_default=True, type=click.Path(exists=True),
              help="Parent directory containing project subdirectories")
@click.option("--dev", is_flag=True,
              help="Dev mode: skip frontend static mount (use Vite dev server instead)")
def serve(host: str, port: int, projects_dir: str, dev: bool):
    """Launch the web server.

    Points at a directory containing one or more project subdirectories.
    Each subdirectory with a state.json is discovered as a project.

    \b
    Examples:
        pipeline serve --projects-dir ~/projects/
        pipeline serve --dev --projects-dir ~/projects/
    """
    try:
        import uvicorn
    except ImportError:
        raise click.ClickException(
            "Web dependencies not installed. Run: pip install -e '.[web]'"
        )
    from novel_to_comic.server.app import create_app
    from novel_to_comic.server.logging import configure_logging

    p = Path(projects_dir).resolve()
    load_config(p)
    configure_logging()
    app = create_app(projects_dir=p, dev=dev)
    console.print(f"[bold]Canary[/bold] → http://{host}:{port}")
    console.print(f"[dim]Projects dir:[/dim] {p}")
    if dev:
        console.print("[dim]Dev mode: frontend served by Vite at http://localhost:5173[/dim]")
    uvicorn.run(app, host=host, port=port, access_log=False, log_config=None)


if __name__ == "__main__":
    cli()
