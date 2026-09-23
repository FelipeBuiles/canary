"""Click CLI entry point — project initialisation and server launch."""

import shutil
from pathlib import Path

import click
from rich.console import Console

from novel_to_comic.config import (
    Config,
    load_config,
    save_config,
)
from novel_to_comic.state import create_initial_state, save_state

console = Console()

@click.group()
def cli():
    """Novel-to-Comic pipeline."""
    pass


@cli.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.option("--name", default=None, help="Project name (default: input filename stem)")
def init(input_path: str, name: str | None):
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

    for subdir in [
        "input",
        "source",
        "brief",
        "samples",
        "refs",
        "plates",
        "adapt",
        "plan",
        "draw",
        "finish",
        "exports",
    ]:
        (project_dir / subdir).mkdir(exist_ok=True)

    dst = project_dir / "input" / src.name
    shutil.copy2(src, dst)

    config = Config()
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
    console.print("\n[dim]Stage models are set in the operator backoffice.[/dim]")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address")
@click.option("--port", default=8000, show_default=True, type=int, help="Port number")
@click.option("--projects-dir", default=".", show_default=True, type=click.Path(exists=True),
              help="Parent directory containing project subdirectories")
@click.option("--dev", is_flag=True,
              help="Dev mode: skip frontend static mount (use Vite dev server instead)")
@click.option("--proxy-headers", is_flag=True,
              help="Trust X-Forwarded-* headers from a reverse proxy (TLS terminator, "
                   "e.g. Fly.io / nginx / a load balancer). Required in production behind "
                   "a proxy so secure cookies and client-IP detection work. Off by default.")
def serve(host: str, port: int, projects_dir: str, dev: bool, proxy_headers: bool):
    """Launch the web server.

    Points at a directory containing one or more project subdirectories.
    Each subdirectory with a state.json is discovered as a project.

    \b
    Examples:
        pipeline serve --projects-dir ~/projects/
        pipeline serve --dev --projects-dir ~/projects/
    """
    from novel_to_comic.codex_dev import CodexRoutingError, enabled, validate_startup

    try:
        validate_startup(host)
        if enabled() and proxy_headers:
            raise CodexRoutingError("Codex development serving cannot trust proxy headers")
    except CodexRoutingError as exc:
        raise click.ClickException(str(exc)) from exc
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
    console.print(f"[bold]Scenewright[/bold] → http://{host}:{port}")
    console.print(f"[dim]Projects dir:[/dim] {p}")
    if dev:
        console.print("[dim]Dev mode: frontend served by Vite at http://localhost:5173[/dim]")
    if proxy_headers:
        console.print("[dim]Proxy headers enabled (trusting X-Forwarded-* from upstream)[/dim]")
    # proxy_headers + forwarded_allow_ips make Uvicorn honour X-Forwarded-Proto / -For
    # so that request.url.scheme and the client IP reflect the real caller. Only enable
    # when explicitly requested — behind no proxy these headers are client-spoofable.
    forwarded_allow_ips = "*" if proxy_headers else None
    uvicorn.run(
        app,
        host=host,
        port=port,
        access_log=False,
        log_config=None,
        proxy_headers=proxy_headers,
        forwarded_allow_ips=forwarded_allow_ips,
    )


if __name__ == "__main__":
    cli()
