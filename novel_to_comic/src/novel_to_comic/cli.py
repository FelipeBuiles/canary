"""Click CLI entry point for the novel-to-comic pipeline."""

import asyncio
import os
import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from novel_to_comic.config import Config, load_config, save_config
from novel_to_comic.state import (
    STAGE_NAMES,
    StageStatus,
    approve_stage,
    create_initial_state,
    get_stale_stages,
    is_stale,
    load_state,
    reset_stale_stages,
    save_state,
)

console = Console()

STAGE_MAP = {
    "extract":    "s1_extract",
    "index":      "s2_index",
    "screenplay": "s3_screenplay",
    "layout-plan": "s4_layout_plan",
    "panels":     "s4_panels",
    "prompts":    "s5_prompts",
    "generate":   "s6_generate",
    "assemble":   "s7_assemble",
}

_INIT_IMAGE_MODEL_CHOICES: list[tuple[str, str]] = [
    ("gemini-3-pro-image-preview", "Gemini 3 Pro Image"),
    ("gemini-2.5-flash-image", "Gemini 2.5 Flash Image"),
    ("gemini-2.5-pro-image", "Gemini 2.5 Pro Image"),
    ("gemini-3.1-flash-image-preview", "Gemini 3.1 Flash Image"),
    ("gemini-3.1-pro-image-preview", "Gemini 3.1 Pro Image"),
    ("gpt-image-1.5", "OpenAI GPT Image 1.5"),
    ("gpt-image-2", "OpenAI GPT Image 2"),
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_project(project: str) -> Path:
    p = Path(project).resolve()
    if not p.exists():
        raise click.ClickException(f"Project directory not found: {p}")
    return p


def _run_async(coro):
    return asyncio.run(coro)


def _load(project: str):
    """Resolve project dir, load config and state together."""
    project_dir = _resolve_project(project)
    try:
        config, env_file = load_config(project_dir)
        from novel_to_comic.server.telemetry import configure_telemetry

        configure_telemetry()
        state = load_state(project_dir)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    # Warn loudly if critical keys are missing so the user isn't left guessing.
    google_ready = config.google_use_vertex_ai or bool(config.gemini_api_key)
    missing = []
    if not google_ready:
        missing.append("GOOGLE_GENAI_USE_VERTEXAI or GEMINI_API_KEY")
    if (
        config.google_use_vertex_ai
        and not config.google_cloud_project
        and not os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    ):
        missing.append("GOOGLE_CLOUD_PROJECT")
    if not config.together_api_key:
        missing.append("TOGETHER_API_KEY")
    if missing:
        src = str(env_file) if env_file else "no .env found"
        console.print(
            f"[yellow]Warning: {', '.join(missing)} not set "
            f"(env source: {src})[/yellow]"
        )

    return project_dir, config, state


def _stage_runners(config, project_dir, state, scene_ids=None, formats=None, retry_failed=False):
    from novel_to_comic.stages import (
        s1_extract, s2_index, s3_screenplay,
        s4_layout_plan, s4_panels, s5_prompts, s6_generate, s7_assemble,
    )
    return {
        "extract":    lambda: s1_extract.run(config, project_dir, state),
        "index":      lambda: s2_index.run(config, project_dir, state),
        "screenplay": lambda: s3_screenplay.run(config, project_dir, state, scene_ids),
        "layout-plan": lambda: s4_layout_plan.run(config, project_dir, state, scene_ids),
        "panels":     lambda: s4_panels.run(config, project_dir, state, scene_ids),
        "prompts":    lambda: s5_prompts.run(config, project_dir, state, scene_ids),
        "generate":   lambda: s6_generate.run(config, project_dir, state, scene_ids, retry_failed),
        "assemble":   lambda: s7_assemble.run(config, project_dir, state, formats, rebuild=True),
    }


def _find_awaiting(state) -> list[str]:
    return [n for n in STAGE_NAMES if state.stages[n].status == StageStatus.AWAITING_REVIEW]


def _print_next(project_dir: Path, stage_name: str) -> None:
    console.print(f"\n[yellow]Paused at checkpoint:[/yellow] [bold]{stage_name}[/bold]")
    console.print("Review the output, then run:")
    console.print(f"  [bold]pipeline approve[/bold]            # approve and keep going")
    console.print(f"  [bold]pipeline approve --stop[/bold]     # approve without continuing")


# ── Commands ──────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Novel-to-Comic: turn any novel into a comic book."""
    pass


# ── init ──────────────────────────────────────────────────────────────────────

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

    # Refuse if the directory already looks like a project
    if (project_dir / "state.json").exists():
        raise click.ClickException(
            f"A project already exists here ({project_dir}).\n"
            f"Delete state.json first, or cd into an empty directory."
        )

    for subdir in ["input", "scenes", "refs", "plates", "screenplays", "layout_plan", "panels",
                   "prompts", "images", "assembly", "exports"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    dst = project_dir / "input" / src.name
    shutil.copy2(src, dst)

    config = Config()
    selected_image_model = (image_model or "").strip() or _choose_image_model(config.image_model)
    config.image_model = selected_image_model
    save_config(config, project_dir)
    state = create_initial_state(project_name, str(dst))
    save_state(state, project_dir)

    # .env.example — shared template; real .env lives at repo/workspace root
    (project_dir / ".env.example").write_text(
        "# API keys — copy to a .env at your repo root (not per-project).\n"
        "# The pipeline walks up from any project dir to find the nearest .env.\n"
        "# Never commit the real .env — add it to your root .gitignore.\n\n"
        "GOOGLE_GENAI_USE_VERTEXAI=true\n"
        "GOOGLE_CLOUD_PROJECT=\n"
        "GOOGLE_CLOUD_LOCATION=global\n"
        "# Optional legacy Gemini Developer API fallback:\n"
        "GEMINI_API_KEY=\n"
        "ANTHROPIC_API_KEY=\n"
        "TOGETHER_API_KEY=\n"
        "OPENAI_API_KEY=\n"
    )

    console.print(f"[green]Project initialised:[/green] {project_dir}")
    console.print(f"\nNext steps:")
    console.print(f"  1. Configure Google ADC / API keys in a [bold].env[/bold] at your repo root")
    console.print(f"  2. [bold]playwright install chromium[/bold]  ← one-time browser install for assembly")
    console.print(f"  3. [bold]pipeline run extract[/bold]")
    console.print(f"  4. [bold]pipeline style[/bold]              ← set visual identity before images")
    console.print(f"  5. [bold]pipeline continue --yes[/bold]     ← run remaining stages automatically")
    console.print(f"\n[dim]Image model set to:[/dim] {config.image_model}")


# ── run (single stage or all) ─────────────────────────────────────────────────

@cli.command()
@click.argument("stage", required=False)
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
@click.option("--scene", default=None, help="Limit to a specific scene ID")
@click.option("--retry-failed", is_flag=True, help="Re-run previously failed items")
@click.option("--format", "export_formats", default=None,
              help="Export formats, comma-separated (pdf,cbz)")
def run(stage: str | None, project: str, scene: str | None,
        retry_failed: bool, export_formats: str | None):
    """Run a single pipeline stage, or all stages if STAGE is omitted.

    Valid stages: extract index screenplay layout-plan panels prompts generate assemble

    Examples:
        pipeline run                        # run all from current dir
        pipeline run generate               # run just image generation
        pipeline run generate --retry-failed
        pipeline run assemble --format pdf
    """
    project_dir, config, state = _load(project)
    scene_ids = [scene] if scene else None
    formats = export_formats.split(",") if export_formats else None

    if stage and stage != "all":
        if stage not in STAGE_MAP:
            raise click.ClickException(
                f"Unknown stage '{stage}'. Valid: {', '.join(STAGE_MAP)}"
            )
        runners = _stage_runners(config, project_dir, state, scene_ids, formats, retry_failed)
        console.print(f"[bold]Running stage: {stage}[/bold]")
        _run_async(runners[stage]())
    else:
        _run_all(config, project_dir, state, scene_ids, formats)


# ── continue ──────────────────────────────────────────────────────────────────

@cli.command("continue")
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
@click.option("--yes", "-y", is_flag=True,
              help="Auto-approve any pending checkpoints and keep going")
@click.option("--format", "export_formats", default=None,
              help="Export formats for assembly, comma-separated (pdf,cbz)")
def continue_pipeline(project: str, yes: bool, export_formats: str | None):
    """Resume the pipeline from where it left off.

    Skips completed stages, auto-detects what to run next.
    If paused at a checkpoint, use --yes to approve and continue automatically.

    Examples:
        pipeline continue
        pipeline continue --yes
        pipeline continue --project ./projects/mynovel
    """
    project_dir, config, state = _load(project)
    formats = export_formats.split(",") if export_formats else None

    # Auto-approve any checkpoint that's blocking progress
    awaiting = _find_awaiting(state)
    if awaiting:
        if yes:
            for stage_name in awaiting:
                approve_stage(state, stage_name)
                save_state(state, project_dir)
                console.print(f"[green]Auto-approved:[/green] {stage_name}")
        else:
            console.print(
                f"[yellow]Pipeline is paused at:[/yellow] [bold]{', '.join(awaiting)}[/bold]\n"
                f"Review the output, then run:\n"
                f"  [bold]pipeline approve[/bold]         # approve and continue\n"
                f"  [bold]pipeline continue --yes[/bold]  # approve automatically and continue"
            )
            return

    _run_all(config, project_dir, state, scene_ids=None, formats=formats)


# ── approve ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
@click.option("--stage", default=None,
              type=click.Choice(list(STAGE_MAP.keys())),
              help="Stage to approve (auto-detected if omitted)")
@click.option("--stop", is_flag=True,
              help="Approve but do NOT continue running — just unblock the stage")
def approve(project: str, stage: str | None, stop: bool):
    """Approve a checkpoint and continue the pipeline.

    The stage to approve is auto-detected from the current pipeline state.
    Use --stop if you only want to unblock without running the next stages.

    Examples:
        pipeline approve              # approve + continue
        pipeline approve --stop       # approve only, don't run next stages
        pipeline approve --stage index
    """
    project_dir, config, state = _load(project)

    # Auto-detect which stage needs approval
    if stage is None:
        awaiting = _find_awaiting(state)
        if not awaiting:
            console.print("[dim]No stages are waiting for approval.[/dim]")
            _print_status_summary(state)
            return
        stage = awaiting[0]
        if len(awaiting) > 1:
            console.print(f"[yellow]Multiple stages awaiting review: {awaiting}[/yellow]")
            console.print(f"Approving: [bold]{stage}[/bold] (first pending)")

    try:
        approve_stage(state, stage)
        save_state(state, project_dir)
    except ValueError as e:
        raise click.ClickException(str(e))

    console.print(f"[green]✓ Approved:[/green] [bold]{stage}[/bold]")

    if stop:
        console.print(f"Run [bold]pipeline continue[/bold] when ready to proceed.")
        return

    console.print()
    _run_all(config, project_dir, state, scene_ids=None, formats=None)


# ── status ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
def status(project: str):
    """Show pipeline progress and costs."""
    project_dir, _, state = _load(project)
    _print_status_summary(state)


def _print_status_summary(state) -> None:
    table = Table(title=f"Pipeline: {state.project_name}")
    table.add_column("Stage", style="bold")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Cost")
    table.add_column("Error", max_width=40)

    styles = {
        StageStatus.PENDING:         "dim",
        StageStatus.RUNNING:         "blue",
        StageStatus.AWAITING_REVIEW: "yellow",
        StageStatus.COMPLETE:        "green",
        StageStatus.FAILED:          "red",
    }

    for name in STAGE_NAMES:
        s = state.stages[name]
        style = styles.get(s.status, "")
        stale_marker = " [yellow](stale)[/yellow]" if is_stale(s) else ""
        progress = ""
        if s.items_total > 0:
            progress = f"{s.items_done}/{s.items_total}"
            if s.items_failed:
                progress += f" ({len(s.items_failed)} failed)"
        table.add_row(
            name,
            f"[{style}]{s.status.value}[/{style}]{stale_marker}",
            progress,
            f"${s.cost_usd:.3f}" if s.cost_usd > 0 else "",
            s.error or "",
        )

    console.print(table)
    console.print(f"\n[bold]Total cost:[/bold] ${state.total_cost_usd:.2f}")

    stale = get_stale_stages(state)
    if stale:
        console.print(f"\n[yellow]Stale running stages detected:[/yellow] {', '.join(stale)}")
        console.print(f"Run [bold]pipeline fix-stale[/bold] to reset them.\n")
        return

    awaiting = [n for n in STAGE_NAMES if state.stages[n].status == StageStatus.AWAITING_REVIEW]
    if awaiting:
        console.print(f"\n[yellow]Checkpoint waiting:[/yellow] [bold]pipeline approve[/bold]")
    else:
        pending = [n for n in STAGE_NAMES
                   if state.stages[n].status not in (StageStatus.COMPLETE, StageStatus.PENDING)]
        if pending:
            console.print(f"\nRun [bold]pipeline continue[/bold] to resume.")


# ── style ─────────────────────────────────────────────────────────────────────

_STYLE_SUGGESTIONS_FILE = "samples/style_suggestions.json"


def _load_suggestions(project_dir: Path) -> list[dict] | None:
    """Load persisted suggestions. Returns None if none exist yet."""
    import json
    path = project_dir / _STYLE_SUGGESTIONS_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("suggestions") if isinstance(data, dict) else data
    except Exception:
        return None


def _save_suggestions(project_dir: Path, suggestions: list[dict], title: str) -> None:
    import json
    path = project_dir / _STYLE_SUGGESTIONS_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"title": title, "suggestions": suggestions}, indent=2))


def _parse_sample_selection(raw: str, n: int) -> list[int]:
    """Parse a sample generation selection string into a sorted list of 1-based indices.

    Accepts:
      "all"        → [1, 2, 3, ..., n]
      "1 3 5"      → [1, 3, 5]
      "1,3,5"      → [1, 3, 5]
      "2-4"        → [2, 3, 4]
      ""  / "n"    → []
    Silently ignores values outside [1, n].
    """
    raw = raw.strip().lower()
    if not raw or raw in ("n", "no", "skip", "none"):
        return []
    if raw in ("all", "a", "y", "yes"):
        return list(range(1, n + 1))

    indices: set[int] = set()
    # Replace commas with spaces, then split on whitespace
    for token in raw.replace(",", " ").split():
        if "-" in token:
            parts = token.split("-", 1)
            try:
                lo, hi = int(parts[0]), int(parts[1])
                indices.update(range(lo, hi + 1))
            except ValueError:
                pass
        else:
            try:
                indices.add(int(token))
            except ValueError:
                pass

    return sorted(i for i in indices if 1 <= i <= n)


@cli.command()
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
@click.option("--refresh", is_flag=True, default=False,
              help="Discard saved suggestions and generate a fresh set.")
def style(project: str, refresh: bool):
    """Suggest and select a visual style template for the comic.

    Reads the Story Bible and generates 5 tailored style options.
    Suggestions are saved to samples/style_suggestions.json so re-running
    shows the same options — use --refresh to generate a new set.

    Sample images are saved per option (style_1.png … style_5.png) so you
    can generate and compare multiple looks without overwriting.

    \b
    Sample generation accepts:
      all        generate all suggestions
      1 3 5      generate specific options (space or comma separated)
      2-4        generate a range
      enter      skip generation
    """
    project_dir, config, _ = _load(project)

    bible_path = project_dir / "story_bible.json"
    if not bible_path.exists():
        raise click.ClickException("story_bible.json not found — run extract first.")

    from novel_to_comic.models.story_bible import StoryBible
    bible = StoryBible.model_validate_json(bible_path.read_text())

    # Load or generate suggestions
    suggestions = None if refresh else _load_suggestions(project_dir)
    if suggestions:
        console.print(
            f"[dim]Loaded saved suggestions for:[/dim] [bold]{bible.title}[/bold]  "
            f"[dim](--refresh to generate new ones)[/dim]"
        )
    else:
        console.print(f"[bold]Generating style suggestions for:[/bold] {bible.title} by {bible.author}")
        suggestions = _run_async(_suggest_styles(config, bible))
        _save_suggestions(project_dir, suggestions, bible.title)

    n = len(suggestions)

    # Identify currently active suggestion (if any matches config)
    active_idx: int | None = None
    for i, s in enumerate(suggestions):
        if isinstance(s, dict) and s.get("template", "").strip() == config.style_template.strip():
            active_idx = i + 1
            break

    # ── Display suggestions ───────────────────────────────────────────────────
    console.print()
    samples_dir = project_dir / "samples"
    for i, s in enumerate(suggestions, 1):
        if not isinstance(s, dict):
            continue
        label       = s.get("label", f"Style {i}")
        active_tag  = " [green]← active[/green]"  if i == active_idx else ""
        sample_tag  = " [dim](sample exists)[/dim]" if (samples_dir / f"style_{i}.png").exists() else ""
        console.print(f"[bold cyan]{i}. {label}[/bold cyan]{active_tag}{sample_tag}")
        console.print(f"   {s.get('template', '')}\n")

    # ── Sample generation (decoupled from selection) ──────────────────────────
    console.print("[dim]Generate samples before choosing? (all / 1 3 5 / 2-4 / enter to skip)[/dim]")
    gen_raw = click.prompt("Samples to generate", default="", show_default=False)
    to_generate = _parse_sample_selection(gen_raw, n)

    if to_generate:
        # Split into: needs generation vs already exists
        need_gen  = [i for i in to_generate if not (samples_dir / f"style_{i}.png").exists()]
        already   = [i for i in to_generate if     (samples_dir / f"style_{i}.png").exists()]

        if already:
            regen_raw = click.prompt(
                f"Samples {already} already exist. Regenerate? (all / numbers / enter to skip)",
                default="",
                show_default=False,
            )
            regen = _parse_sample_selection(regen_raw, n)
            # Deduplicate: keep existing unless explicitly asked to regen
            need_gen = sorted(set(need_gen) | (set(already) & set(regen)))

        if need_gen:
            console.print(f"[bold]Generating {len(need_gen)} sample(s): {need_gen}[/bold]")
            _run_async(_generate_style_samples_parallel(config, bible, project_dir, need_gen, suggestions))

            # Refresh sample_exists tags after generation
            console.print()
            for i in need_gen:
                p = samples_dir / f"style_{i}.png"
                label = suggestions[i - 1].get("label", f"Style {i}") if i <= n else f"Style {i}"
                if p.exists():
                    console.print(f"  [green]✓[/green] style_{i}.png  ({label})")
                else:
                    console.print(f"  [red]✗[/red] style_{i}.png  generation failed")
            console.print()

    # ── Style selection ───────────────────────────────────────────────────────
    current_preview = config.style_template[:80] + ("..." if len(config.style_template) > 80 else "")
    console.print(f"[dim]Current: {current_preview}[/dim]\n")

    choice = click.prompt(
        f"Set active style [1-{n}], 0 for custom, enter to keep current",
        default=str(active_idx) if active_idx else "",
        show_default=bool(active_idx),
    )

    # Treat empty input as "keep"
    if not str(choice).strip():
        console.print("[dim]Keeping current style.[/dim]")
        return

    try:
        choice_i = int(choice)
    except (ValueError, TypeError):
        console.print("[dim]Keeping current style.[/dim]")
        return

    if choice_i == 0:
        new_template = click.prompt("Enter custom style template")
    elif 1 <= choice_i <= n:
        new_template = suggestions[choice_i - 1]["template"]
    else:
        console.print("[dim]Keeping current style.[/dim]")
        return

    config.style_template = new_template
    save_config(config, project_dir)
    console.print("[green]Style template saved to config.yaml.[/green]")


async def _generate_style_sample(
    config: Config, bible, project_dir: Path, sample_path: Path
) -> None:
    """Generate one sample panel image to preview a style template."""
    from novel_to_comic.clients import flux
    from novel_to_comic.prompting import build_style_sample_prompt

    prompt = build_style_sample_prompt(config, bible)

    sample_path.parent.mkdir(exist_ok=True)
    try:
        await flux.generate_image(config=config, prompt=prompt, output_path=sample_path)
    except Exception as e:
        console.print(f"[yellow]  style_{sample_path.stem}: generation failed — {e}[/yellow]")


async def _generate_style_samples_parallel(
    config: Config,
    bible,
    project_dir: Path,
    indices: list[int],
    suggestions: list[dict],
) -> None:
    """Generate sample images for the given suggestion indices."""
    from novel_to_comic.clients.flux import _is_gemini_native

    samples_dir = project_dir / "samples"
    samples_dir.mkdir(exist_ok=True)

    async def _one(idx: int) -> None:
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = samples_dir / f"style_{idx}.png"
        await _generate_style_sample(sample_config, bible, project_dir, sample_path)

    if _is_gemini_native(config.effective_image_model()):
        for i in indices:
            await _one(i)
        return

    await asyncio.gather(*[_one(i) for i in indices])


async def _suggest_styles(config: Config, bible) -> list[dict]:
    from novel_to_comic.clients import gemini

    system = (
        "You are a visual art director for adapted fiction. Given a story's details, generate 5 "
        "distinct visual style templates for image generation prompts. "
        "Span the full medium spectrum — do NOT default to illustrated or comic styles. "
        "At least one suggestion must be photorealistic or cinematic. "
        "Include a range: e.g. cinematic live-action, painterly, stylised illustration, graphic novel, "
        "anime/manga — pick whichever 5 best suit this specific story. "
        "Each is a single paragraph of 40-70 words describing: medium/rendering style, color palette, "
        "lighting, composition, mood. Make each genuinely distinct. Output a JSON array only, no markdown."
    )
    user = (
        f'Story: "{bible.title}" by {bible.author}\n'
        f"Style notes: {bible.style_notes or 'none'}\n"
        f"Genre/tone: {', '.join({s.scene_type for s in bible.scenes})}\n"
        f"Characters: {'; '.join(f'{c.name} ({c.gender}, {c.age_range})' for c in bible.characters[:5])}\n\n"
        f"Generate 5 style options that genuinely serve this story. "
        f"Consider what rendering style would best capture the tone — not just what looks 'comic-like'. "
        f"Output JSON array of 5 objects: "
        f'[{{"label": "Style Name (2-4 words)", "template": "40-70 word description"}}, ...]'
    )

    result = await gemini.generate_json(
        config=config, model=config.screenplay_model,
        system_prompt=system, user_content=user,
    )
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("styles", [])
    return []


# ── config ────────────────────────────────────────────────────────────────────

@cli.command("config")
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
def show_config(project: str):
    """Show resolved configuration and auth sources for this project.

    Useful for diagnosing missing or wrong credentials.

    Example:
        pipeline config
        pipeline config --project ./projects/monkeypaw
    """
    project_dir = _resolve_project(project)
    try:
        config, env_file = load_config(project_dir)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    def _mask(val: str) -> str:
        if not val:
            return "[red]NOT SET[/red]"
        return f"[green]{val[:8]}…{val[-4:]}[/green]" if len(val) > 12 else "[green]set[/green]"

    console.print(f"\n[bold]Project:[/bold]  {project_dir}")
    console.print(f"[bold].env file:[/bold] {env_file or '[yellow]not found — walking up from project dir[/yellow]'}")
    console.print()

    table = Table(title="Google Auth", show_header=True)
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("google_use_vertex_ai", "[green]true[/green]" if config.google_use_vertex_ai else "[yellow]false[/yellow]")
    table.add_row("google_cloud_project", config.google_cloud_project or "[yellow]from environment/ADC[/yellow]")
    table.add_row("google_cloud_location", config.google_cloud_location or "[yellow]global[/yellow]")
    console.print(table)

    console.print()
    table = Table(title="API Keys", show_header=True)
    table.add_column("Variable")
    table.add_column("Value")
    table.add_column("Source")
    for env_name, field in [
        ("GEMINI_API_KEY",    config.gemini_api_key),
        ("ANTHROPIC_API_KEY", config.anthropic_api_key),
        ("TOGETHER_API_KEY",  config.together_api_key),
        ("OPENAI_API_KEY",    config.openai_api_key),
    ]:
        import os as _os
        in_shell = bool(_os.environ.get(env_name, "").strip())
        source = "shell env" if in_shell else (".env" if env_file and field else "not found")
        table.add_row(env_name, _mask(field), source)
    console.print(table)

    console.print()
    table2 = Table(title="Models")
    table2.add_column("Stage")
    table2.add_column("Model")
    for label, val in [
        ("extraction",  config.extraction_model),
        ("screenplay",  config.screenplay_model),
        ("panels",      config.panel_model),
        ("prompts",     config.prompt_model),
        ("rag index",   "enabled" if config.enable_rag_index else "disabled"),
        ("embeddings",  config.embedding_model),
        ("image",       config.image_model),
        ("fallback img",config.fallback_image_model),
    ]:
        table2.add_row(label, val)
    console.print(table2)


# ── export ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
@click.option("--format", "export_formats", default="pdf,cbz", show_default=True,
              help="Export formats, comma-separated (pdf,cbz)")
@click.option("--from-json", "from_json", is_flag=True,
              help="Re-render existing page JSON without rebuilding. "
                   "Use after editing assembly/pages/page_NNN.json directly.")
@click.option("--rebuild", is_flag=True,
              help="Force rebuild page JSON from panel data even if JSON already exists.")
def export(project: str, export_formats: str, from_json: bool, rebuild: bool):
    """Render comic pages to PDF/CBZ.

    Default: re-render existing page JSON files (respects any edits).
    Use --rebuild to regenerate page JSON from panel data first.

    Workflow for manual bubble editing:
        1. Edit  assembly/pages/page_NNN.json  (set bubble x/y coordinates)
        2. Run   pipeline export               (re-renders, picks up your edits)

    Examples:
        pipeline export
        pipeline export --format pdf
        pipeline export --rebuild
    """
    project_dir, config, state = _load(project)
    from novel_to_comic.stages import s7_assemble

    # Determine whether to rebuild JSON from panel data
    json_dir = project_dir / "assembly" / "pages"
    has_json = json_dir.exists() and any(json_dir.glob("page_*.json"))

    if from_json and rebuild:
        raise click.ClickException("--from-json and --rebuild are mutually exclusive.")

    # If explicit flags are given, honour them.
    # If neither flag, use existing JSON if present (render-only), else full build.
    do_rebuild = rebuild or (not from_json and not has_json)

    _run_async(s7_assemble.run(
        config, project_dir, state,
        formats=export_formats.split(","),
        rebuild=do_rebuild,
    ))


# ── regen ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
@click.option("--scene", required=True, help="Scene ID to regenerate panels from (e.g. scene_001)")
@click.option("--skip-prompts", is_flag=True,
              help="Keep the existing prompt JSON — only regenerate the image. "
                   "Use this if you edited prompts/<scene>/panel_NNN.json directly.")
@click.argument("panel_numbers", nargs=-1, type=int, required=True)
def regen(project: str, scene: str, skip_prompts: bool, panel_numbers: tuple[int, ...]):
    """Re-generate specific panels by number.

    Workflow:
      1. Edit the panel JSON in panels/<scene>/panel_NNN.json
      2. Run:  pipeline regen --scene scene_001 3 5 7
      3. Run:  pipeline export   (to rebuild the comic pages)

    The command deletes the cached prompt JSON and panel image for each
    requested panel, then re-runs stages 5 and 6 for those panels only.
    Other panels in the scene are skipped (already cached).

    Use --skip-prompts if you have edited prompts/<scene>/panel_NNN.json
    directly and only want a fresh image, not a fresh prompt.

    Examples:
        pipeline regen --scene scene_001 3 5 7
        pipeline regen --scene scene_001 --skip-prompts 3
    """
    project_dir, config, state = _load(project)
    from novel_to_comic.stages import s5_prompts, s6_generate

    cleared: list[str] = []
    for num in panel_numbers:
        tag = f"panel_{num:03d}"
        if not skip_prompts:
            p = project_dir / "prompts" / scene / f"{tag}.json"
            if p.exists():
                p.unlink()
                cleared.append(f"prompts/{scene}/{tag}.json")
        img = project_dir / "images" / scene / f"{tag}.png"
        if img.exists():
            img.unlink()
            cleared.append(f"images/{scene}/{tag}.png")

    if cleared:
        console.print("[dim]Cleared cached files:[/dim]")
        for f in cleared:
            console.print(f"  [dim]{f}[/dim]")
    else:
        console.print("[yellow]No cached files found for the requested panels.[/yellow]")

    if not skip_prompts:
        console.print(f"\n[bold]Stage 5: Regenerating prompts for {scene}...[/bold]")
        _run_async(s5_prompts.run(config, project_dir, state, scene_ids=[scene]))

    console.print(f"\n[bold]Stage 6: Regenerating images for {scene}...[/bold]")
    _run_async(s6_generate.run(config, project_dir, state, scene_ids=[scene]))

    console.print(f"\n[green]Done.[/green] Run [bold]pipeline export[/bold] to rebuild the comic pages.")


# ── fix-stale ──────────────────────────────────────────────────────────────────

@cli.command("fix-stale")
@click.option("--project", default=".", show_default=True, type=click.Path(),
              help="Project directory")
def fix_stale(project: str):
    """Detect and reset stale RUNNING stages back to PENDING.

    A stage gets stuck in RUNNING when the pipeline server was restarted mid-run
    or the process crashed. No server-side process is tracking it, but state.json
    still says it's running.

    Examples:
        pipeline fix-stale
        pipeline fix-stale --project ./projects/mynovel
    """
    project_dir, _, state = _load(project)
    stale = get_stale_stages(state)
    if not stale:
        console.print("[dim]No stale stages detected.[/dim]")
        return

    console.print(f"[yellow]Stale stages detected:[/yellow] {', '.join(stale)}")
    if not click.confirm("Reset these stages to PENDING?", default=True):
        console.print("[dim]Aborted.[/dim]")
        return

    reset = reset_stale_stages(state)
    save_state(state, project_dir)
    console.print(f"[green]Reset:[/green] {', '.join(reset)}")
    console.print("Run [bold]pipeline continue[/bold] to re-run.")


# ── serve (web dashboard) ────────────────────────────────────────────────────

@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Bind address")
@click.option("--port", default=8000, show_default=True, type=int,
              help="Port number")
@click.option("--projects-dir", default=".", show_default=True, type=click.Path(exists=True),
              help="Parent directory containing project subdirectories")
@click.option("--dev", is_flag=True,
              help="Dev mode: skip frontend static mount (use Vite dev server instead)")
def serve(host: str, port: int, projects_dir: str, dev: bool):
    """Launch the web dashboard.

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
    # Ensure .env is loaded (walking up from --projects-dir) before logging/
    # telemetry initialization so CANARY_OTEL_ENABLED and OTEL_* vars are visible.
    load_config(p)
    configure_logging()
    app = create_app(projects_dir=p, dev=dev)
    console.print(f"[bold]Canary dashboard[/bold] → http://{host}:{port}")
    console.print(f"[dim]Projects dir:[/dim] {p}")
    if dev:
        console.print("[dim]Dev mode: frontend served by Vite at http://localhost:5173[/dim]")
    uvicorn.run(app, host=host, port=port, access_log=False, log_config=None)


# ── internal: run all ─────────────────────────────────────────────────────────

def _run_all(config, project_dir, state, scene_ids, formats):
    """Run all pending stages in order, pausing at checkpoints."""
    runners = _stage_runners(config, project_dir, state, scene_ids, formats)

    if config.style_template.strip() == Config().style_template.strip():
        console.print(
            "[yellow]⚠  style_template is still the default boilerplate.[/yellow]\n"
            f"   Run [bold]pipeline style[/bold] to pick a visual identity, then continue."
        )
        if not click.confirm("Continue anyway?", default=False):
            return

    for stage_name in STAGE_NAMES:
        s = state.stages[stage_name]

        if s.status == StageStatus.COMPLETE:
            console.print(f"[dim]  ✓ {stage_name}[/dim]")
            continue

        if s.status == StageStatus.AWAITING_REVIEW:
            _print_next(project_dir, stage_name)
            return

        console.print(f"\n[bold]{'─' * 48}[/bold]")
        console.print(f"[bold]  Stage: {stage_name}[/bold]")
        console.print(f"[bold]{'─' * 48}[/bold]")
        _run_async(runners[stage_name]())

        # Re-read state after stage runs (it modifies it)
        s = state.stages[stage_name]
        if s.status == StageStatus.AWAITING_REVIEW:
            _print_next(project_dir, stage_name)
            return

    console.print("\n[bold green]Pipeline complete![/bold green]")
    console.print(f"Total cost: ${state.total_cost_usd:.2f}")


if __name__ == "__main__":
    cli()
