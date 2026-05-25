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
    run: Callable  # async def run(config, project_dir, state, on_event) -> Any
    outputs: Callable[[Path], list[Path]]
    clean_paths: Callable[[Path], list[Path]]
    estimate_cost: Callable[[Config, Path, PipelineState], float] | None = None


# Deferred to avoid circular import: stage modules import Stage from here,
# and Stage must be defined before those modules are loaded.
from novel_to_comic.stages import (  # noqa: E402
    s1_extract,
    s2_style,
    s3_cast,
    s4_screenplay,
    s5_layout_plan,
    s5_panels,
    s6_storyboard,
    s7_draw,
    s8_compose,
)

REGISTRY: dict[str, Stage] = {
    m.STAGE.name: m.STAGE
    for m in [
        s1_extract,
        s2_style,
        s3_cast,
        s4_screenplay,
        s5_layout_plan,
        s5_panels,
        s6_storyboard,
        s7_draw,
        s8_compose,
    ]
}
