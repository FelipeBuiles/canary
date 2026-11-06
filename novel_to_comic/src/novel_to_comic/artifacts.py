"""Canonical artifact paths and typed read/write helpers for all pipeline stages.

Every stage reads inputs and writes outputs through these functions. Path
construction knowledge lives here and nowhere else — if a directory layout
changes, this is the only file that needs updating.

This module owns Story, Style, and Cast assets. They are series-level Look
assets: every path resolves against the series root (see ``workspace.py``), so
each part workspace reads the same Story Bible and references. Full-page
pipeline artifacts live behind :class:`novel_to_comic.target_artifacts.TargetArtifacts`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    from novel_to_comic.models.story_bible import StoryBible


from novel_to_comic.target_artifacts import ArtifactMissing
from novel_to_comic.workspace import series_root


# ---------------------------------------------------------------------------
# Story Bible
# ---------------------------------------------------------------------------

def story_bible_path(project_dir: Path) -> Path:
    return series_root(project_dir) / "story_bible.json"


def read_story_bible(project_dir: Path) -> "StoryBible":
    from novel_to_comic.models.story_bible import StoryBible
    from novel_to_comic.target_artifacts import ArtifactInvalid
    path = story_bible_path(project_dir)
    if not path.exists():
        raise ArtifactMissing("story_bible", path)
    try:
        return StoryBible.model_validate_json(path.read_text())
    except ValidationError as exc:
        raise ArtifactInvalid("story_bible", path, exc) from exc


def read_story_bible_safe(project_dir: Path) -> "StoryBible | None":
    """Return the story bible, or None when missing/unparseable.

    For best-effort paths (cost estimation, optional context) that must not
    raise. Hard-requirement paths should use read_story_bible.
    """
    try:
        return read_story_bible(project_dir)
    except Exception:
        return None


def write_story_bible(project_dir: Path, bible: "StoryBible") -> None:
    # Atomic: parts read the series Story Bible while another part or an
    # author edit writes it, so a reader must never see a partial file.
    path = story_bible_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(bible.model_dump_json(indent=2))
    temporary.replace(path)


# ---------------------------------------------------------------------------
# Asset sidecar helpers (shared by refs and plates)
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
    # Atomic: page jobs read reference metadata while an author keeps an image.
    path = asset_meta_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(meta, indent=2, sort_keys=True))
    temporary.replace(path)


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
    return series_root(project_dir) / "refs" / char_id / "sheet.png"


def character_ref_pose_path(project_dir: Path, char_id: str, pose: str) -> Path:
    return series_root(project_dir) / "refs" / char_id / f"{pose}.png"


def character_ref_meta_path(project_dir: Path, char_id: str) -> Path:
    return asset_meta_path(character_ref_sheet_path(project_dir, char_id))


def character_ref_instructions_path(project_dir: Path, char_id: str) -> Path:
    return series_root(project_dir) / "refs" / char_id / "instructions.jsonl"


def character_state_ref_sheet_path(project_dir: Path, char_id: str, state_id: str) -> Path:
    return series_root(project_dir) / "refs" / char_id / "states" / state_id / "sheet.png"


def character_state_ref_instructions_path(
    project_dir: Path, char_id: str, state_id: str
) -> Path:
    return series_root(project_dir) / "refs" / char_id / "states" / state_id / "instructions.jsonl"


CHARACTER_REF_POSES = ("portrait", "full_body")


def primary_refs_path(project_dir: Path) -> Path:
    return series_root(project_dir) / "refs" / "primary_refs.json"


def read_primary_refs(project_dir: Path) -> dict[str, str]:
    """Legacy/Dev Content pose override per character."""
    path = primary_refs_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_primary_refs(project_dir: Path, data: dict[str, str]) -> None:
    path = primary_refs_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Location plates (plates)
# ---------------------------------------------------------------------------

def location_plate_path(project_dir: Path, loc_id: str) -> Path:
    return series_root(project_dir) / "plates" / f"{loc_id}.png"


def location_plate_meta_path(project_dir: Path, loc_id: str) -> Path:
    return asset_meta_path(location_plate_path(project_dir, loc_id))


def location_plate_instructions_path(project_dir: Path, loc_id: str) -> Path:
    return series_root(project_dir) / "plates" / f"{loc_id}.instructions.jsonl"


def location_state_plate_path(project_dir: Path, loc_id: str, state_id: str) -> Path:
    return series_root(project_dir) / "plates" / loc_id / "states" / f"{state_id}.png"


def location_state_plate_instructions_path(
    project_dir: Path, loc_id: str, state_id: str
) -> Path:
    return series_root(project_dir) / "plates" / loc_id / "states" / f"{state_id}.instructions.jsonl"


# ---------------------------------------------------------------------------
# Prop reference images (refs/props)
# ---------------------------------------------------------------------------

def prop_ref_path(project_dir: Path, prop_id: str) -> Path:
    return series_root(project_dir) / "refs" / "props" / prop_id / "ref.png"


def prop_ref_meta_path(project_dir: Path, prop_id: str) -> Path:
    return asset_meta_path(prop_ref_path(project_dir, prop_id))


def prop_ref_instructions_path(project_dir: Path, prop_id: str) -> Path:
    return series_root(project_dir) / "refs" / "props" / prop_id / "instructions.jsonl"


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
            if isinstance(addendum, str) and (addendum.strip() or payload.get("operation") == "restore"):
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
    return series_root(project_dir) / "samples" / "style_suggestions.json"


def style_sample_path(project_dir: Path, index: int) -> Path:
    return series_root(project_dir) / "samples" / f"style_{index}.png"


def style_sample_brief_path(project_dir: Path) -> Path:
    return series_root(project_dir) / "samples" / "style_sample_brief.json"


def style_proof_copy_path(project_dir: Path) -> Path:
    return series_root(project_dir) / "samples" / "style_proof_copy.json"


def style_direction_path(project_dir: Path, direction_id: str) -> Path:
    import re

    if not re.fullmatch(r"direction_[a-f0-9]{16}", direction_id or ""):
        raise ValueError("invalid style direction id")
    root = series_root(project_dir).resolve()
    base = (root / "samples" / "directions").resolve()
    candidate = (base / direction_id / "direction.json").resolve()
    if not base.is_relative_to(root) or not candidate.is_relative_to(base):
        raise ValueError("style direction path escapes project")
    return candidate


def style_direction_image_path(project_dir: Path, direction_id: str, suffix: str) -> Path:
    if suffix not in {".png", ".jpg", ".webp"}:
        raise ValueError("invalid style direction image suffix")
    direction_dir = style_direction_path(project_dir, direction_id).parent
    candidate = (direction_dir / f"reference{suffix}").resolve()
    if candidate.parent != direction_dir:
        raise ValueError("style direction image path escapes project")
    return candidate


def reference_upload_path(project_dir: Path, upload_id: str, suffix: str) -> Path:
    """An author-uploaded Cast correction reference, content-addressed in the series root."""
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", upload_id or "") or suffix not in {".png", ".jpg", ".webp", ".json"}:
        raise ValueError("invalid reference upload")
    return series_root(project_dir) / "reference_uploads" / f"{upload_id}{suffix}"


def style_validation_path(project_dir: Path, suggestion_id: str) -> Path:
    import re

    if not re.fullmatch(r"style_[a-f0-9]{16}", suggestion_id or ""):
        raise ValueError("invalid style suggestion id")
    root = series_root(project_dir).resolve()
    base = (root / "samples" / "validations").resolve()
    candidate = (base / f"{suggestion_id}.png").resolve()
    if not base.is_relative_to(root) or candidate.parent != base:
        raise ValueError("style validation path escapes project")
    return candidate


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def export_pdf_path(project_dir: Path) -> Path:
    return project_dir / "exports" / "comic.pdf"


def export_cbz_path(project_dir: Path) -> Path:
    return project_dir / "exports" / "comic.cbz"


def prop_state_ref_path(project_dir: Path, prop_id: str, state_id: str) -> Path:
    return series_root(project_dir) / "refs" / "props" / prop_id / "states" / state_id / "ref.png"
