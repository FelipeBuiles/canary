"""Stage 8: Panel images → ComicPage JSON → HTML → PNG → PDF/CBZ.

Two distinct responsibilities:

1. BUILD  — reads panel images + PanelBreakdown data, groups them into pages,
             and writes ``compose/pages/page_NNN.json`` (ComicPage models).
             These JSON files are the canonical editing surface — the web
             dashboard edits them via the pages REST API, and the next
             render picks up the changes.

2. RENDER — reads ComicPage JSON → builds HTML → Playwright screenshot → PNG
             → PDF / CBZ export.

``run(..., rebuild=True)``   →  build + render (full stage run)
``run(..., rebuild=False)``  →  render only (respects any JSON edits;
                                 used by ``POST /api/projects/{id}/export/``)
"""

import re
import tempfile
import zipfile
from pathlib import Path

import img2pdf
from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.assembly.html_renderer import (
    browser_context,
    build_page_html,
    render_html_to_png,
    resolve_theme,
    write_theme_css,
)
from novel_to_comic.config import Config
from novel_to_comic.events import make_progress
from novel_to_comic.layout_planning import (
    image_path_for_panel,
    load_layout_plan,
    persist_projected_pages,
    planned_panel_index,
    planned_panel_to_breakdown,
)
from novel_to_comic.models.comic_page import (
    Bubble,
    ComicPage,
    PagePanel,
    Sfx,
    infer_sfx_intensity,
    infer_sfx_kind,
    normalize_sfx_text,
)
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.stage_runtime import StageRuntime

console = Console()


# ── Build: panel data → ComicPage JSON ───────────────────────────────────────

def _collect_panel_data(project_dir: Path) -> list[tuple[Path, PanelBreakdown]]:
    """Collect ordered (img_path, breakdown) pairs from the draw/storyboard dirs.

    Only used when no layout plan exists; the plan path goes through
    ``_collect_page_groups_from_layout_plan`` instead.
    """
    images_dir = project_dir / "draw"
    panels_dir = project_dir / "storyboard"
    panel_data: list[tuple[Path, PanelBreakdown]] = []

    for scene_dir in sorted(images_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        scene_id = scene_dir.name
        for img_path in sorted(scene_dir.glob("panel_*.png")):
            m = re.search(r"panel_(\d+)", img_path.stem)
            if not m:
                console.print(f"[yellow]Skipping non-standard filename: {img_path.name}[/yellow]")
                continue
            panel_num = m.group(1)
            bd_path = panels_dir / scene_id / f"panel_{panel_num}.json"
            if bd_path.exists():
                bd = PanelBreakdown.model_validate_json(bd_path.read_text())
            else:
                bd = PanelBreakdown(
                    scene_id=scene_id, panel_number=int(panel_num),
                    shot_type="medium", camera_angle="eye-level",
                    characters_present=[], character_actions={},
                    character_expressions={}, character_positions={},
                    background_description="", lighting="", mood="",
                )
            panel_data.append((img_path, bd))

    return panel_data


def _collect_page_groups_from_layout_plan(project_dir: Path) -> list[list[tuple[Path, PanelBreakdown]]]:
    plan = load_layout_plan(project_dir)
    panel_lookup = planned_panel_index(plan)
    page_groups: list[list[tuple[Path, PanelBreakdown]]] = []
    for page in plan.planned_pages:
        group: list[tuple[Path, PanelBreakdown]] = []
        for panel_id in page.panel_ids:
            planned_panel = panel_lookup.get(panel_id)
            if planned_panel is None:
                continue
            img_path = image_path_for_panel(project_dir, planned_panel)
            if not img_path.exists():
                continue
            group.append((img_path, planned_panel_to_breakdown(planned_panel)))
        if group:
            page_groups.append(group)
    return page_groups


def _group_into_pages(
    panel_data: list[tuple[Path, PanelBreakdown]],
    max_per_page: int,
) -> list[list[tuple[Path, PanelBreakdown]]]:
    pages, current = [], []
    for item in panel_data:
        if len(current) >= max_per_page:
            pages.append(current)
            current = []
        current.append(item)
    if current:
        pages.append(current)
    return pages


def _build_comic_page(
    group: list[tuple[Path, PanelBreakdown]],
    page_number: int,
    project_dir: Path,
    story_bible: StoryBible,
    theme_name: str,
) -> ComicPage:
    """Convert a list of (image_path, PanelBreakdown) into a ComicPage model."""
    n = len(group)
    layout = str(n) if n <= 6 else "many"

    char_name_map = {c.id: c.name.split()[0] for c in story_bible.characters}

    panels: list[PagePanel] = []
    for idx, (img_path, bd) in enumerate(group):
        # Store image path relative to project_dir for portability
        try:
            rel_img = str(img_path.relative_to(project_dir))
        except ValueError:
            rel_img = str(img_path)

        # Character side lookup from position strings
        char_sides: dict[str, str] = {}
        for cid, pos in bd.character_positions.items():
            p = pos.lower()
            char_sides[cid] = "right" if "right" in p else ("center" if "center" in p else "left")

        # Show speaker labels when 3+ characters share the panel
        show_labels = len(bd.characters_present) >= 3
        _alt = ["left", "right"]
        _alt_idx = 0

        bubbles: list[Bubble] = []
        for bi, dl in enumerate(bd.dialogue):
            is_narration = dl.type == "narration"
            side = char_sides.get(dl.character_id)
            if side is None and not is_narration:
                side = _alt[_alt_idx % 2]
                _alt_idx += 1
            bubbles.append(Bubble(
                id=f"{bd.scene_id}-p{bd.panel_number}-b{bi}",
                type=dl.type if dl.type in ("speech", "thought", "narration") else "speech",
                text=dl.text,
                speaker_id=dl.character_id or None,
                speaker_name=char_name_map.get(dl.character_id) if show_labels else None,
                source_beat_id=dl.source_beat_id,
                source_text=dl.source_text,
                narration_mode=dl.narration_mode,
                preferred_zone=dl.preferred_zone,
                side=side or "left",
            ))

        # Standard layout grid overrides (CSS nth-child handles these by default;
        # we store them anyway so the web editor can read the intended placement)
        grid_column: str | None = None
        if layout == "3" and idx == 0:
            grid_column = "1 / 3"
        elif layout == "5" and idx == 0:
            grid_column = "1 / 3"
        elif layout == "5" and idx == 1:
            grid_column = "3"

        sfx_items: list[Sfx] = []
        for raw in bd.sfx:
            text = normalize_sfx_text(raw)
            if not text:
                continue
            sfx_items.append(Sfx(
                text=text,
                kind=infer_sfx_kind(text),
                intensity=infer_sfx_intensity(text),
            ))
        panels.append(PagePanel(
            id=f"{bd.scene_id}-{bd.panel_number:03d}",
            image_path=rel_img,
            scene_id=bd.scene_id,
            panel_number=bd.panel_number,
            bubbles=bubbles,
            sfx=sfx_items,
            grid_column=grid_column,
        ))

    return ComicPage(
        page_number=page_number,
        theme=theme_name,
        layout=layout,
        panels=panels,
    )


# ── Export helpers ────────────────────────────────────────────────────────────

def _get_compressed_images(page_paths: list[Path], tmp_dir: str) -> list[Path]:
    """Convert page PNGs to compressed JPEGs in a temporary directory."""
    from PIL import Image
    compressed_paths = []
    for idx, png_path in enumerate(page_paths):
        jpg_path = Path(tmp_dir) / f"page_{idx + 1:03d}.jpg"
        with Image.open(png_path) as img:
            rgb_img = img.convert("RGB")
            rgb_img.save(jpg_path, "JPEG", quality=85, optimize=True)
        compressed_paths.append(jpg_path)
    return compressed_paths


def _export_pdf(compressed_paths: list[Path], output_path: Path) -> None:
    if not compressed_paths:
        return
    with open(output_path, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in compressed_paths]))


def _export_cbz(compressed_paths: list[Path], output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, path in enumerate(compressed_paths):
            zf.write(path, f"page_{i + 1:03d}.jpg")


def _do_exports(page_paths: list[Path], exports_dir: Path, formats: list[str]) -> None:
    if not page_paths:
        return

    console.print("[dim]Compressing page images for export...[/dim]")

    with tempfile.TemporaryDirectory() as tmp_dir:
        compressed_paths = _get_compressed_images(page_paths, tmp_dir)

        if "pdf" in formats:
            pdf_path = exports_dir / "comic.pdf"
            _export_pdf(compressed_paths, pdf_path)
            console.log(f"[green]PDF:[/green] {pdf_path}")
        if "cbz" in formats:
            cbz_path = exports_dir / "comic.cbz"
            _export_cbz(compressed_paths, cbz_path)
            console.log(f"[green]CBZ:[/green] {cbz_path}")


# ── Render: ComicPage JSON → HTML → PNG → exports ────────────────────────────

async def _render_and_export(
    json_paths: list[Path],
    html_dir: Path,
    png_dir: Path,
    project_dir: Path,
    custom_css: str,
    exports_dir: Path,
    export_formats: list[str],
    ctx: StageRuntime,
) -> None:
    """Render each page JSON to HTML + PNG, then write PDF/CBZ exports."""
    async with browser_context() as browser:
        with make_progress(ctx.on_event) as progress:
            task = progress.add_task("Rendering pages", total=len(json_paths))
            png_paths: list[Path] = []
            for json_path in json_paths:
                comic_page   = ComicPage.model_validate_json(json_path.read_text())
                html_content = build_page_html(comic_page, project_dir, custom_css)

                html_path = html_dir / f"page_{comic_page.page_number:03d}.html"
                html_path.write_text(html_content, encoding="utf-8")

                png_path = png_dir / f"page_{comic_page.page_number:03d}.png"
                await render_html_to_png(
                    html_content, png_path,
                    browser=browser, source_path=html_path,
                )
                png_paths.append(png_path)
                ctx.record_item_done()
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)

    _do_exports(png_paths, exports_dir, export_formats)
    for fmt in export_formats:
        out = exports_dir / f"comic.{fmt}"
        ctx.log(f"{fmt.upper()}: {out}")


# ── Public stage entry points ─────────────────────────────────────────────────

async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    formats: list[str] | None = None,
    rebuild: bool = True,
) -> None:
    """Compose stage: build ComicPage JSON (if rebuild=True), then render to PNG/PDF/CBZ."""
    export_formats = formats or ["pdf", "cbz"]
    max_per_page   = getattr(config, "max_panels_per_page", 6)

    # ── Validate inputs ───────────────────────────────────────────────────────
    images_dir = project_dir / "draw"
    if not images_dir.exists() or not any(images_dir.iterdir()):
        console.print("[red]No images found. Run the draw stage first.[/red]")
        ctx.log("No images found. Run the draw stage first.", level="error")
        return

    story_bible = artifacts.read_story_bible(project_dir)

    # ── Directories ───────────────────────────────────────────────────────────
    assembly_dir = project_dir / "compose"
    json_dir  = assembly_dir / "pages"      # ComicPage JSON (editing surface)
    html_dir  = assembly_dir / "html"       # HTML previews (open in browser)
    png_dir   = assembly_dir / "pages"      # PNGs share the dir with JSON
    exports_dir = artifacts.export_pdf_path(project_dir).parent
    for d in (json_dir, html_dir, exports_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── Theme ─────────────────────────────────────────────────────────────────
    theme_name = resolve_theme(config)
    css_path   = write_theme_css(project_dir, theme_name)
    custom_css = css_path.read_text()
    console.print(f"[dim]Theme:[/dim] {theme_name}")
    console.print(
        f"[dim]Edit [bold]{css_path.relative_to(project_dir)}[/bold] "
        f"then run [bold]pipeline export[/bold] to apply changes.[/dim]"
    )
    ctx.log(f"Theme: {theme_name}")

    # ── Build phase (panel data → ComicPage JSON) ─────────────────────────────
    if rebuild:
        plan_path = artifacts.layout_plan_path(project_dir)
        if plan_path.exists():
            page_groups = _collect_page_groups_from_layout_plan(project_dir)
            if not page_groups:
                console.print("[red]No valid panel images found.[/red]")
                ctx.log("No valid panel images found.", level="error")
                return
            panel_count = sum(len(group) for group in page_groups)
            # persist_projected_pages prunes stale page JSON before writing
            projected_pages = persist_projected_pages(project_dir, story_bible, theme_name)
            json_paths = [
                json_dir / f"page_{page.page_number:03d}.json"
                for page in projected_pages
            ]
            source_desc = " from layout plan"
        else:
            panel_data = _collect_panel_data(project_dir)
            if not panel_data:
                console.print("[red]No valid panel images found.[/red]")
                ctx.log("No valid panel images found.", level="error")
                return
            page_groups = _group_into_pages(panel_data, max_per_page)
            panel_count = len(panel_data)
            # Prune stale page JSON from a previous, larger build so render-only
            # runs and the pages API never pick up ghost pages.
            for old in json_dir.glob("page_*.json"):
                old.unlink()
            json_paths = []
            for i, group in enumerate(page_groups):
                comic_page = _build_comic_page(group, i + 1, project_dir, story_bible, theme_name)
                artifacts.write_compose_page(project_dir, i + 1, comic_page)
                json_paths.append(artifacts.compose_page_path(project_dir, i + 1))
            source_desc = f" ({max_per_page}/page)"

        with ctx.execute(total=len(json_paths)):
            console.print(
                f"[bold]Building {panel_count} panels → {len(json_paths)} pages{source_desc}...[/bold]"
            )
            ctx.log(f"Building {panel_count} panels → {len(json_paths)} pages", level="bold")
            ctx.save()
            console.print(f"[dim]Page JSON files in:[/dim] [bold]{json_dir.relative_to(project_dir)}[/bold]")
            ctx.log(f"Page JSON files in: {json_dir.relative_to(project_dir)}", level="dim")

            await _render_and_export(
                json_paths, html_dir, png_dir, project_dir,
                custom_css, exports_dir, export_formats, ctx,
            )

            console.print(
                f"[dim]HTML previews in:[/dim] [bold]{html_dir.relative_to(project_dir)}[/bold]  "
                f"(open in browser to preview, edit theme.css, hard-refresh)"
            )
            ctx.log(f"HTML previews in: {html_dir.relative_to(project_dir)}", level="dim")
            console.print("[green]Compose stage complete.[/green]")
    else:
        # Render-only: load existing JSON
        json_paths = sorted(json_dir.glob("page_*.json"))
        if not json_paths:
            console.print("[red]No page JSON files found. Run the compose stage first.[/red]")
            ctx.log("No page JSON files found.", level="error")
            return

        with ctx.execute(total=len(json_paths)):
            console.print(f"[bold]Re-rendering {len(json_paths)} existing page(s)...[/bold]")
            await _render_and_export(
                json_paths, html_dir, png_dir, project_dir,
                custom_css, exports_dir, export_formats, ctx,
            )
            console.print("[green]Compose stage complete.[/green]")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402

STAGE = Stage(
    name="compose",
    run=run,
    outputs=lambda d: [d / "exports"],
    clean_paths=lambda d: clean_cascade(d, "compose"),
)
