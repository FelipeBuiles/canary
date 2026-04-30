"""Pipeline stages — each stage is a pure function from files to files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Stage:
    name: str
    run: Callable  # async def run(config, project_dir, state, on_event) -> Any
    outputs: Callable[[Path], list[Path]]
    clean_paths: Callable[[Path], list[Path]]


# Deferred to avoid circular import: stage modules import Stage from here,
# and Stage must be defined before those modules are loaded.
from novel_to_comic.stages import (  # noqa: E402
    s1_extract,
    s2_index,
    s3_screenplay,
    s4_layout_plan,
    s4_panels,
    s5_prompts,
    s6_generate,
    s7_assemble,
)

REGISTRY: dict[str, Stage] = {
    m.STAGE.name: m.STAGE
    for m in [
        s1_extract,
        s2_index,
        s3_screenplay,
        s4_layout_plan,
        s4_panels,
        s5_prompts,
        s6_generate,
        s7_assemble,
    ]
}
