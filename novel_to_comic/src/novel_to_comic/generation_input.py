"""Provider-independent prompt inputs for Style and Cast assets."""

from __future__ import annotations

from dataclasses import dataclass

from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.image_geometry import GenerationShape


@dataclass(frozen=True, slots=True)
class GenerationPromptInput:
    """Canonical prompt input for one Style or Cast image asset."""

    anchors: tuple[PromptAnchor, ...] = ()
    subjects: tuple[PromptSubject, ...] = ()
    composition: str | None = None
    setting: str | None = None
    lighting: str | None = None
    mood: str | None = None
    props: tuple[str, ...] = ()
    key_objects: tuple[str, ...] = ()
    visual_requirements: tuple[str, ...] = ()
    continuity_note: str | None = None
    visual_brief: str | None = None
    distilled_prompt: str | None = None
    full_prompt: str | None = None
    style: str | None = None
    constraints: str | None = None
    editorial_addendum: str = ""
    editable_facets: tuple[str, ...] = ()
    crop_policy: str | None = None
    has_narration_caption: bool = False
    location_state_id: str | None = None
    source_sha256: str | None = None
    width: int = 1024
    height: int = 1024
    generation_width: int | None = None
    generation_height: int | None = None
    generation_shape: GenerationShape | None = None
    generation_aspect_ratio: float | None = None


__all__ = ["GenerationPromptInput"]
