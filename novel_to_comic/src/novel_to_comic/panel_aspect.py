"""Canonical panel generation aspect helpers."""

from __future__ import annotations

from typing import Literal

GenerationShape = Literal["portrait", "landscape", "square"]
GenerationAspectSource = Literal["page_geometry", "panel_shape", "shot_default"]

PORTRAIT_SIZE = (768, 1024)
SQUARE_SIZE = (1024, 1024)
LANDSCAPE_SIZE = (1344, 768)
ASPECT_TOLERANCE = 0.12


def generation_shape_for_aspect(aspect_ratio: float | None) -> GenerationShape:
    if aspect_ratio is None or aspect_ratio <= 0:
        return "square"
    if aspect_ratio < 0.9:
        return "portrait"
    if aspect_ratio > 1.15:
        return "landscape"
    return "square"


def dimensions_for_generation_shape(shape: str | None) -> tuple[int, int]:
    if shape == "portrait":
        return PORTRAIT_SIZE
    if shape == "landscape":
        return LANDSCAPE_SIZE
    return SQUARE_SIZE


def dimensions_for_generation_aspect(aspect_ratio: float | None) -> tuple[int, int]:
    shape = generation_shape_for_aspect(aspect_ratio)
    if shape == "landscape" and aspect_ratio is not None and aspect_ratio <= 1.6:
        return 1536, 1024
    if shape == "portrait" and aspect_ratio is not None and aspect_ratio >= 0.7:
        return 768, 1024
    return dimensions_for_generation_shape(shape)


def aspect_for_dimensions(width: int | None, height: int | None) -> float | None:
    if not width or not height or width <= 0 or height <= 0:
        return None
    return width / height


def aspect_within_tolerance(
    actual_aspect: float | None,
    requested_aspect: float | None,
    *,
    tolerance: float = ASPECT_TOLERANCE,
) -> bool:
    if actual_aspect is None or requested_aspect is None or requested_aspect <= 0:
        return True
    return abs((actual_aspect / requested_aspect) - 1.0) <= tolerance


def frame_phrase(shape: str | None) -> str:
    if shape == "portrait":
        return "vertical portrait frame"
    if shape == "landscape":
        return "wide horizontal frame"
    return "square frame"


def aspect_instruction(shape: str | None, aspect_ratio: float | None = None) -> str:
    phrase = frame_phrase(shape)
    if aspect_ratio and aspect_ratio > 0:
        return f"Output aspect ratio must be {shape or 'square'} (about {aspect_ratio:.2f}:1). Fill one {phrase}."
    return f"Output must fill one {phrase}."
