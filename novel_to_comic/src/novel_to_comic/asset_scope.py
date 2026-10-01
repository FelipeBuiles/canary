"""Project containment for Cast asset reads and writes."""

from pathlib import Path

from novel_to_comic.workspace import series_root


def require_project_asset_path(project_dir: Path, path: Path) -> Path:
    # Cast assets are series-level, so a part workspace is contained by its root.
    root = series_root(project_dir).resolve()
    candidate = path.resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise ValueError("Cast asset path escapes its project")
    return path
