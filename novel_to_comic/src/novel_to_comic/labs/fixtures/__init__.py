"""Built-in labs fixtures."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent
DEFAULT_SCENE_PATH = FIXTURES_DIR / "sample_scene.json"
REFERENCE_IMAGES_DIR = FIXTURES_DIR / "reference_images"


@lru_cache(maxsize=1)
def default_scene() -> dict[str, Any]:
    return json.loads(DEFAULT_SCENE_PATH.read_text())


def reference_image_paths(scene: dict[str, Any] | None = None) -> list[Path]:
    scene = scene or default_scene()
    paths: list[Path] = []
    for ref in scene.get("reference_images") or []:
        name = ref.get("filename") if isinstance(ref, dict) else None
        if not name:
            continue
        p = REFERENCE_IMAGES_DIR / name
        if p.exists():
            paths.append(p)
    return paths
