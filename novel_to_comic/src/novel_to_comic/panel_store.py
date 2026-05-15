"""Panel store — owns panel record read/write across its lifecycle (s5 → s9).

Routes and stages should call these instead of reaching into ``artifacts`` and
then manually re-rendering / re-distilling.  Centralising the operations here
means the "read → validate → patch → re-render → write" pipeline has one owner
and callers can't omit steps (e.g. forgetting to re-derive ``full_prompt`` after
editing prompt fields).
"""

from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.prompt_assembly import rerender_prompt_body
from novel_to_comic.prompting import generate_distilled_prompt


def load_breakdown(project_dir: Path, scene_id: str, panel_number: int) -> PanelBreakdown | None:
    """Return the PanelBreakdown for a panel, or None if the file doesn't exist."""
    path = artifacts.panel_breakdown_path(project_dir, scene_id, panel_number)
    if not path.exists():
        return None
    return PanelBreakdown.model_validate_json(path.read_text())


def save_breakdown(
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    data: dict,
) -> PanelBreakdown:
    """Validate ``data`` as a PanelBreakdown and persist it.

    Returns the validated model so callers can use the canonical representation.
    Raises ``ValueError`` if ``data`` fails validation.
    """
    updated = PanelBreakdown.model_validate(data)
    artifacts.write_panel_breakdown(project_dir, scene_id, panel_number, updated)
    return updated


def load_prompt(project_dir: Path, scene_id: str, panel_number: int) -> ImagePrompt | None:
    """Return the ImagePrompt for a panel, or None if the file doesn't exist."""
    path = artifacts.panel_prompt_path(project_dir, scene_id, panel_number)
    if not path.exists():
        return None
    return ImagePrompt.model_validate_json(path.read_text())


def save_prompt(
    project_dir: Path,
    scene_id: str,
    panel_number: int,
    data: dict,
) -> ImagePrompt:
    """Validate ``data`` as an ImagePrompt, re-derive rendered fields, and persist.

    Re-derives ``full_prompt`` from the structured fields and regenerates
    ``distilled_prompt`` so callers can't accidentally leave them stale after
    editing prompt fields.

    Returns the updated model.  Raises ``ValueError`` if ``data`` fails validation.
    """
    updated = ImagePrompt.model_validate(data)
    updated.full_prompt = rerender_prompt_body(updated)
    updated.distilled_prompt = generate_distilled_prompt(updated)
    artifacts.write_panel_prompt(project_dir, scene_id, panel_number, updated)
    return updated
