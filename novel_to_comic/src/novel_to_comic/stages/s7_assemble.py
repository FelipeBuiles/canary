"""Stage 7: Panel images → ComicPage JSON → HTML → PNG → PDF/CBZ.

Two distinct responsibilities:

1. BUILD  — reads panel images + PanelBreakdown data, groups them into pages,
             and writes ``assembly/pages/page_NNN.json`` (ComicPage models).
             These JSON files are the canonical editing surface.  Edit them
             directly or via the future web dashboard; the next export picks
             up your changes.

2. RENDER — reads ComicPage JSON → builds HTML → Playwright screenshot → PNG
             → PDF / CBZ export.

``pipeline run assemble``  →  build + render (full path)
``pipeline export``         →  render only (respects any JSON edits you've made)
``pipeline export --rebuild``  →  build + render (force fresh JSON)

Web dashboard path (future):
    GET  /api/pages/         →  serve page JSON files
    PATCH /api/pages/1/      →  save edits (bubble positions, theme, layout)
    POST /api/export/        →  trigger render_pages() → download PDF
"""

import re
import zipfile
from pathlib import Path

import img2pdf
from rich.console import Console
from rich.progress import Progress

from novel_to_comic import artifacts
from novel_to_comic.assembly.html_renderer import (
    browser_context,
    build_page_html,
    render_html_to_png,
    resolve_theme,
    write_theme_css,
)
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP, make_progress
from novel_to_comic.layout_planning import (
    image_path_for_panel,
    load_layout_plan,
    persist_projected_pages,
    planned_panel_index,
    planned_panel_to_breakdown,
)
from novel_to_comic.models.comic_page import Bubble, ComicPage, PagePanel, Sfx
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    save_state,
)

console = Console()


# ── Build: panel data → ComicPage JSON ───────────────────────────────────────

def _collect_panel_data(
    project_dir: Path,
    use_layout_plan: bool = True,
) -> list[tuple[Path, PanelBreakdown]]:
    """Collect ordered (img_path, breakdown) pairs, preferring layout plan ordering."""
    if use_layout_plan:
        plan_path = project_dir / "plan" / "layout_plan.json"
        if plan_path.exists():
            plan = load_layout_plan(project_dir)
            panel_lookup = planned_panel_index(plan)
            panel_data: list[tuple[Path, PanelBreakdown]] = []
            for page in plan.planned_pages:
                for panel_id in page.panel_ids:
                    planned_panel = panel_lookup.get(panel_id)
                    if planned_panel is None:
                        continue
                    img_path = image_path_for_panel(project_dir, planned_panel)
                    if not img_path.exists():
                        continue
                    panel_data.append((img_path, planned_panel_to_breakdown(planned_panel)))
            return panel_data

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

        panels.append(PagePanel(
            id=f"{bd.scene_id}-{bd.panel_number:03d}",
            image_path=rel_img,
            scene_id=bd.scene_id,
            panel_number=bd.panel_number,
            bubbles=bubbles,
            sfx=Sfx(text=bd.sfx) if bd.sfx else None,
            grid_column=grid_column,
        ))

    return ComicPage(
        page_number=page_number,
        theme=theme_name,
        layout=layout,
        panels=panels,
    )


# ── Export helpers ────────────────────────────────────────────────────────────

def _export_pdf(page_paths: list[Path], output_path: Path) -> None:
    if not page_paths:
        return
    with open(output_path, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in page_paths]))


def _export_cbz(page_paths: list[Path], output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, path in enumerate(page_paths):
            zf.write(path, f"page_{i + 1:03d}.png")


def _do_exports(page_paths: list[Path], exports_dir: Path, formats: list[str]) -> None:
    if "pdf" in formats:
        pdf_path = exports_dir / "comic.pdf"
        _export_pdf(page_paths, pdf_path)
        console.print(f"[green]PDF:[/green] {pdf_path}")
    if "cbz" in formats:
        cbz_path = exports_dir / "comic.cbz"
        _export_cbz(page_paths, cbz_path)
        console.print(f"[green]CBZ:[/green] {cbz_path}")


# ── Public stage entry points ─────────────────────────────────────────────────

async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    formats: list[str] | None = None,
    rebuild: bool = True,
    on_event: EventCallback | None = None,
) -> None:
    """Stage 7: build ComicPage JSON (if rebuild=True), then render to PNG/PDF/CBZ."""
    emit = on_event or _NOOP
    export_formats = formats or ["pdf", "cbz"]
    max_per_page   = getattr(config, "max_panels_per_page", 6)

    # ── Validate inputs ───────────────────────────────────────────────────────
    images_dir = project_dir / "draw"
    if not images_dir.exists() or not any(images_dir.iterdir()):
        console.print("[red]No images found. Run stage 6 (generate) first.[/red]")
        emit({"type": "log", "stage": "compose", "level": "error",
              "message": "No images found. Run stage 6 (generate) first."})
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
    emit({"type": "log", "stage": "compose", "level": "info",
          "message": f"Theme: {theme_name}"})

    # ── Build phase (panel data → ComicPage JSON) ─────────────────────────────
    if rebuild:
        plan_path = artifacts.layout_plan_path(project_dir)
        panel_data = _collect_panel_data(project_dir, use_layout_plan=plan_path.exists())
        if not panel_data:
            console.print("[red]No valid panel images found.[/red]")
            emit({"type": "log", "stage": "compose", "level": "error",
                  "message": "No valid panel images found."})
            return

        begin_stage(state, "compose", total=len(panel_data))
        emit({"type": "stage_begin", "stage": "compose", "total": len(panel_data)})
        save_state(state, project_dir)

        if plan_path.exists():
            projected_pages = persist_projected_pages(project_dir, story_bible, theme_name)
            page_groups = _collect_page_groups_from_layout_plan(project_dir)
            json_paths = [
                json_dir / f"page_{page.page_number:03d}.json"
                for page in projected_pages
            ]
        else:
            page_groups = _group_into_pages(panel_data, max_per_page)
            json_paths = []
        console.print(
            f"[bold]Building {len(panel_data)} panels → "
            f"{len(page_groups)} pages{' from layout plan' if plan_path.exists() else f' ({max_per_page}/page)'}...[/bold]"
        )
        emit({"type": "log", "stage": "compose", "level": "bold",
              "message": f"Building {len(panel_data)} panels → {len(page_groups)} pages"})
        if not plan_path.exists():
            for i, group in enumerate(page_groups):
                comic_page = _build_comic_page(group, i + 1, project_dir, story_bible, theme_name)
                artifacts.write_compose_page(project_dir, i + 1, comic_page)
                json_paths.append(artifacts.compose_page_path(project_dir, i + 1))
        for group in page_groups:
            for _ in group:
                record_item_done(state, "compose")
                emit({"type": "stage_progress", "stage": "compose",
                      "done": state.stages["compose"].items_done,
                      "total": state.stages["compose"].items_total})
        save_state(state, project_dir)
        console.print(f"[dim]Page JSON files in:[/dim] [bold]{json_dir.relative_to(project_dir)}[/bold]")
        emit({"type": "log", "stage": "compose", "level": "dim",
              "message": f"Page JSON files in: {json_dir.relative_to(project_dir)}"})
    else:
        # Render-only: load existing JSON
        json_paths = sorted(json_dir.glob("page_*.json"))
        if not json_paths:
            console.print("[red]No page JSON files found. Run without --from-json first.[/red]")
            emit({"type": "log", "stage": "compose", "level": "error",
                  "message": "No page JSON files found."})
            return
        begin_stage(state, "compose", total=len(json_paths))
        emit({"type": "stage_begin", "stage": "compose", "total": len(json_paths)})
        save_state(state, project_dir)
        console.print(f"[bold]Re-rendering {len(json_paths)} existing page(s)...[/bold]")

    # ── Render phase (ComicPage JSON → HTML → PNG) ────────────────────────────
    try:
        async with browser_context() as browser:
            with make_progress(on_event) as progress:
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
                    progress.advance(task)

        console.print(
            f"[dim]HTML previews in:[/dim] [bold]{html_dir.relative_to(project_dir)}[/bold]  "
            f"(open in browser to preview, edit theme.css, hard-refresh)"
        )
        emit({"type": "log", "stage": "compose", "level": "dim",
              "message": f"HTML previews in: {html_dir.relative_to(project_dir)}"})

        _do_exports(png_paths, exports_dir, export_formats)
        for fmt in export_formats:
            out = exports_dir / f"comic.{fmt}"
            emit({"type": "log", "stage": "compose", "level": "info",
                  "message": f"{fmt.upper()}: {out}"})

        complete_stage(state, "compose")
        emit({"type": "stage_complete", "stage": "compose",
              "done": state.stages["compose"].items_done,
              "total": state.stages["compose"].items_total})
        save_state(state, project_dir)
        console.print("[green]Stage 8 complete.[/green]")

    except Exception as e:
        fail_stage(state, "compose", str(e))
        emit({"type": "stage_fail", "stage": "compose", "message": str(e)})
        save_state(state, project_dir)
        raise


from novel_to_comic.stages import Stage  # noqa: E402

STAGE = Stage(
    name="compose",
    run=run,
    outputs=lambda d: [d / "exports"],
    clean_paths=lambda d: [d / "compose", d / "exports"],
)
