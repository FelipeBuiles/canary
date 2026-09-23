"""Project containment for Cast asset reads and writes."""

from pathlib import Path


def require_project_asset_path(project_dir: Path, path: Path) -> Path:
    root = project_dir.resolve()
    candidate = path.resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise ValueError("Cast asset path escapes its project")
    return path
