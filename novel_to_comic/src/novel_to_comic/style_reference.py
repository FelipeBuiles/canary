"""Resolve the selected raw Style proof for downstream visual conditioning."""

import json
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.style_contract import page_style_template, style_template_for_suggestion


def find_style_reference(project_dir: Path, style_template: str) -> Path | None:
    """Match the complete selected direction; never substitute a nearby style."""
    try:
        data = json.loads(artifacts.style_suggestions_path(project_dir).read_text())
        active = page_style_template(style_template)
        for index, suggestion in enumerate(data.get("suggestions", []), 1):
            if isinstance(suggestion, dict) and style_template_for_suggestion(suggestion) == active:
                path = artifacts.style_sample_path(project_dir, index)
                if path.is_file():
                    return path
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return None


def require_style_reference(project_dir: Path, style_template: str) -> Path:
    path = find_style_reference(project_dir, style_template)
    if path is None:
        raise ValueError(
            "The selected Style proof is missing or does not match the current style. "
            "Rerun Style and select a proof before generating artwork."
        )
    return path
