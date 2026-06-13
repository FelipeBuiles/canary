"""Load/save the project-level LetteringStyle (assembly/lettering_style.json)."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.models.lettering import LetteringStyle


def lettering_style_path(project_dir: Path) -> Path:
    return project_dir / "assembly" / "lettering_style.json"


def load_lettering_style(project_dir: Path) -> LetteringStyle:
    """Return the project's lettering style, or a golden-age default if unset."""
    path = lettering_style_path(project_dir)
    if not path.exists():
        return LetteringStyle()
    return LetteringStyle.model_validate_json(path.read_text())


def save_lettering_style(project_dir: Path, style: LetteringStyle) -> None:
    path = lettering_style_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(style.model_dump_json(indent=2))
