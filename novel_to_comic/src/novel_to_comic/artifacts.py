"""Canonical artifact paths and typed read/write helpers for all pipeline stages.

Every stage reads inputs and writes outputs through these functions. Path
construction knowledge lives here and nowhere else — if a directory layout
changes, this is the only file that needs updating.

Conventions:
- Read functions raise ArtifactMissing when the file does not exist.
- Write functions create parent directories automatically.
- List functions return only artifacts that exist on disk.
- Panel numbers match PlannedPanel.panel_number (1-indexed, zero-padded to 3 digits).
- Page numbers are 1-indexed, zero-padded to 3 digits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from novel_to_comic.models.comic_page import ComicPage
    from novel_to_comic.models.layout_plan import LayoutPlan
    from novel_to_comic.models.panel import PanelBreakdown, Screenplay
    from novel_to_comic.models.prompt import ImagePrompt
    from novel_to_comic.models.story_bible import StoryBible


class ArtifactMissing(Exception):
    def __init__(self, name: str, path: Path) -> None:
        super().__init__(f"Artifact '{name}' not found: {path}")
        self.name = name
        self.path = path


# ---------------------------------------------------------------------------
# Story Bible
# ---------------------------------------------------------------------------

def story_bible_path(project_dir: Path) -> Path:
    return project_dir / "story_bible.json"


def read_story_bible(project_dir: Path) -> "StoryBible":
    from novel_to_comic.models.story_bible import StoryBible
    path = story_bible_path(project_dir)
    if not path.exists():
        raise ArtifactMissing("story_bible", path)
    return StoryBible.model_validate_json(path.read_text())


def write_story_bible(project_dir: Path, bible: "StoryBible") -> None:
    path = story_bible_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bible.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Scene text
# ---------------------------------------------------------------------------

def scene_text_path(project_dir: Path, scene_id: str) -> Path:
    return project_dir / "scenes" / f"{scene_id}.txt"


def read_scene_text(project_dir: Path, scene_id: str) -> str:
    path = scene_text_path(project_dir, scene_id)
    if not path.exists():
        raise ArtifactMissing("scene_text", path)
    return path.read_text()


def write_scene_text(project_dir: Path, scene_id: str, text: str) -> None:
    path = scene_text_path(project_dir, scene_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ---------------------------------------------------------------------------
# Screenplay
# ---------------------------------------------------------------------------

def screenplay_path(project_dir: Path, scene_id: str) -> Path:
    return project_dir / "screenplays" / f"{scene_id}.json"


def read_screenplay(project_dir: Path, scene_id: str) -> "Screenplay":
    from novel_to_comic.models.panel import Screenplay
    path = screenplay_path(project_dir, scene_id)
    if not path.exists():
        raise ArtifactMissing("screenplay", path)
    return Screenplay.model_validate_json(path.read_text())


def write_screenplay(project_dir: Path, scene_id: str, screenplay: "Screenplay") -> None:
    path = screenplay_path(project_dir, scene_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(screenplay.model_dump_json(indent=2))


def list_screenplays(project_dir: Path) -> list["Screenplay"]:
    from novel_to_comic.models.panel import Screenplay
    sp_dir = project_dir / "screenplays"
    if not sp_dir.exists():
        return []
    results = []
    for p in sorted(sp_dir.glob("*.json")):
        try:
            results.append(Screenplay.model_validate_json(p.read_text()))
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# Layout plan
# ---------------------------------------------------------------------------

def layout_plan_path(project_dir: Path) -> Path:
    return project_dir / "plan" / "layout_plan.json"


def read_layout_plan(project_dir: Path) -> "LayoutPlan":
    from novel_to_comic.models.layout_plan import LayoutPlan
    path = layout_plan_path(project_dir)
    if not path.exists():
        raise ArtifactMissing("layout_plan", path)
    return LayoutPlan.model_validate_json(path.read_text())


def write_layout_plan(project_dir: Path, plan: "LayoutPlan") -> None:
    path = layout_plan_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Panel breakdown (storyboard)
# ---------------------------------------------------------------------------

def panel_breakdown_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "storyboard" / scene_id / f"panel_{panel_number:03d}.json"


def read_panel_breakdown(project_dir: Path, scene_id: str, panel_number: int) -> "PanelBreakdown":
    from novel_to_comic.models.panel import PanelBreakdown
    path = panel_breakdown_path(project_dir, scene_id, panel_number)
    if not path.exists():
        raise ArtifactMissing("panel_breakdown", path)
    return PanelBreakdown.model_validate_json(path.read_text())


def write_panel_breakdown(
    project_dir: Path, scene_id: str, panel_number: int, breakdown: "PanelBreakdown"
) -> None:
    path = panel_breakdown_path(project_dir, scene_id, panel_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(breakdown.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Image prompts (direct)
# ---------------------------------------------------------------------------

def panel_prompt_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "direct" / scene_id / f"panel_{panel_number:03d}.json"


def read_panel_prompt(project_dir: Path, scene_id: str, panel_number: int) -> "ImagePrompt":
    from novel_to_comic.models.prompt import ImagePrompt
    path = panel_prompt_path(project_dir, scene_id, panel_number)
    if not path.exists():
        raise ArtifactMissing("panel_prompt", path)
    return ImagePrompt.model_validate_json(path.read_text())


def write_panel_prompt(
    project_dir: Path, scene_id: str, panel_number: int, prompt: "ImagePrompt"
) -> None:
    path = panel_prompt_path(project_dir, scene_id, panel_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt.model_dump_json(indent=2))


def list_panel_prompts(project_dir: Path, scene_id: str) -> list["ImagePrompt"]:
    from novel_to_comic.models.prompt import ImagePrompt
    scene_dir = project_dir / "direct" / scene_id
    if not scene_dir.exists():
        return []
    results = []
    for p in sorted(scene_dir.glob("panel_*.json")):
        try:
            results.append(ImagePrompt.model_validate_json(p.read_text()))
        except Exception:
            pass
    return results


def list_all_panel_prompts(project_dir: Path) -> list["ImagePrompt"]:
    from novel_to_comic.models.prompt import ImagePrompt
    prompts_dir = project_dir / "direct"
    if not prompts_dir.exists():
        return []
    results = []
    for p in sorted(prompts_dir.glob("*/panel_*.json")):
        try:
            results.append(ImagePrompt.model_validate_json(p.read_text()))
        except Exception:
            pass
    return results


def panel_prompt_instructions_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "direct" / scene_id / f"panel_{panel_number:03d}.instructions.jsonl"


# ---------------------------------------------------------------------------
# Panel images (draw)
# ---------------------------------------------------------------------------

def panel_image_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png"


def panel_image_meta_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png.meta.json"


def panel_image_failure_path(project_dir: Path, scene_id: str, panel_number: int) -> Path:
    return project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png.failure.json"


def list_panel_images(project_dir: Path, scene_id: str) -> list[Path]:
    scene_dir = project_dir / "draw" / scene_id
    if not scene_dir.exists():
        return []
    return sorted(scene_dir.glob("panel_*.png"))


# ---------------------------------------------------------------------------
# Asset sidecar helpers (shared by refs, plates, draw images)
# ---------------------------------------------------------------------------

def asset_meta_path(output_path: Path) -> Path:
    return output_path.with_suffix(f"{output_path.suffix}.meta.json")


def asset_failure_path(output_path: Path) -> Path:
    return output_path.with_suffix(f"{output_path.suffix}.failure.json")


def read_asset_meta(output_path: Path) -> dict:
    path = asset_meta_path(output_path)
    if not path.exists():
        raise ArtifactMissing("asset_meta", path)
    return json.loads(path.read_text())


def write_asset_meta(output_path: Path, meta: dict) -> None:
    path = asset_meta_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True))


def write_asset_failure(output_path: Path, payload: dict) -> None:
    path = asset_failure_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def asset_matches_meta(output_path: Path, expected: dict) -> bool:
    if not output_path.exists():
        return False
    try:
        actual = read_asset_meta(output_path)
    except (ArtifactMissing, Exception):
        return False
    return actual == expected


# ---------------------------------------------------------------------------
# Character references (refs)
# ---------------------------------------------------------------------------

def character_ref_sheet_path(project_dir: Path, char_id: str) -> Path:
    return project_dir / "refs" / char_id / "sheet.png"


def character_ref_pose_path(project_dir: Path, char_id: str, pose: str) -> Path:
    return project_dir / "refs" / char_id / f"{pose}.png"


def character_ref_meta_path(project_dir: Path, char_id: str) -> Path:
    return asset_meta_path(character_ref_sheet_path(project_dir, char_id))


def character_ref_instructions_path(project_dir: Path, char_id: str) -> Path:
    return project_dir / "refs" / char_id / "instructions.jsonl"


# ---------------------------------------------------------------------------
# Location plates (plates)
# ---------------------------------------------------------------------------

def location_plate_path(project_dir: Path, loc_id: str) -> Path:
    return project_dir / "plates" / f"{loc_id}.png"


def location_plate_meta_path(project_dir: Path, loc_id: str) -> Path:
    return asset_meta_path(location_plate_path(project_dir, loc_id))


def location_plate_instructions_path(project_dir: Path, loc_id: str) -> Path:
    return project_dir / "plates" / f"{loc_id}.instructions.jsonl"


def read_active_addendum(instructions_path: Path) -> str:
    """Return the addendum from the most recent accepted instruction, or ""."""
    if not instructions_path.exists():
        return ""
    last: str = ""
    try:
        for line in instructions_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            addendum = payload.get("patch", {}).get("addendum")
            if isinstance(addendum, str) and addendum.strip():
                last = addendum.strip()
    except Exception:
        return ""
    return last


def append_instruction_log_entry(instructions_path: Path, payload: dict) -> None:
    instructions_path.parent.mkdir(parents=True, exist_ok=True)
    with instructions_path.open("a") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Style samples
# ---------------------------------------------------------------------------

def style_suggestions_path(project_dir: Path) -> Path:
    return project_dir / "samples" / "style_suggestions.json"


def style_sample_path(project_dir: Path, index: int) -> Path:
    return project_dir / "samples" / f"style_{index}.png"


# ---------------------------------------------------------------------------
# Compose pages
# ---------------------------------------------------------------------------

def compose_page_path(project_dir: Path, page_number: int) -> Path:
    return project_dir / "compose" / "pages" / f"page_{page_number:03d}.json"


def compose_page_html_path(project_dir: Path, page_number: int) -> Path:
    return project_dir / "compose" / "html" / f"page_{page_number:03d}.html"


def compose_page_png_path(project_dir: Path, page_number: int) -> Path:
    return project_dir / "compose" / "pages" / f"page_{page_number:03d}.png"


def read_compose_page(project_dir: Path, page_number: int) -> "ComicPage":
    from novel_to_comic.models.comic_page import ComicPage
    path = compose_page_path(project_dir, page_number)
    if not path.exists():
        raise ArtifactMissing("compose_page", path)
    return ComicPage.model_validate_json(path.read_text())


def write_compose_page(project_dir: Path, page_number: int, page: "ComicPage") -> None:
    path = compose_page_path(project_dir, page_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page.model_dump_json(indent=2))


def compose_pages_dir(project_dir: Path) -> Path:
    return project_dir / "compose" / "pages"


def list_compose_pages(project_dir: Path) -> list["ComicPage"]:
    from novel_to_comic.models.comic_page import ComicPage
    pages_dir = compose_pages_dir(project_dir)
    if not pages_dir.exists():
        return []
    results = []
    for p in sorted(pages_dir.glob("page_*.json")):
        try:
            results.append(ComicPage.model_validate_json(p.read_text()))
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def export_pdf_path(project_dir: Path) -> Path:
    return project_dir / "exports" / "comic.pdf"


def export_cbz_path(project_dir: Path) -> Path:
    return project_dir / "exports" / "comic.cbz"
