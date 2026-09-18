"""Pipeline stages — each stage is a pure function from files to files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from novel_to_comic.config import Config
    from novel_to_comic.state import PipelineState


@dataclass
class Stage:
    name: str
    run: Callable  # async def run(config, project_dir, ctx) -> Any
    outputs: Callable[[Path], list[Path]]
    clean_paths: Callable[[Path], list[Path]]
    estimate_cost: Callable[[Config, Path, PipelineState], float] | None = None


# Artifact directories in pipeline order. Re-running a stage invalidates its
# own outputs plus everything downstream, so each stage's clean_paths is just
# the cascade from its first directory.
_CLEAN_CASCADE: tuple[str, ...] = (
    "source",
    "brief",
    "samples",
    "refs",
    "plates",
    "adapt",
    "plan",
    "lettering",
    "draw",
    "finish",
    "exports",
)


def clean_cascade(project_dir: Path, start: str) -> list[Path]:
    """Return the artifact directories from *start* to the end of the pipeline."""
    names = _CLEAN_CASCADE[_CLEAN_CASCADE.index(start):]
    paths = []
    for name in names:
        if (name == "lettering" and start in {"refs", "plates", "adapt", "plan"}
                and (project_dir / "lettering" / "style.json").exists()):
            # The book style belongs to Style; page layouts belong to Plan/Pages.
            paths.extend(child for child in sorted((project_dir / "lettering").iterdir())
                         if child.name != "style.json")
        else:
            paths.append(project_dir / name)
    return paths


# Deferred to avoid circular import: stage modules import Stage from here,
# and Stage must be defined before those modules are loaded.
from novel_to_comic.stages import (  # noqa: E402
    s1_extract,
    s2_brief,
    s2_style,
    s3_cast,
    s4_adapt,
    s5_plan,
    s7_page_draw,
    s8_finish,
)

REGISTRY: dict[str, Stage] = {
    m.STAGE.name: m.STAGE
    for m in [
        s1_extract,
        s2_brief,
        s2_style,
        s3_cast,
        s4_adapt,
        s5_plan,
        s7_page_draw,
        s8_finish,
    ]
}
