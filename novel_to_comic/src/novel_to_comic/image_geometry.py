"""Canonical image-generation aspect helpers."""

from __future__ import annotations

from typing import Literal

GenerationShape = Literal["portrait", "landscape", "square"]
GenerationAspectSource = Literal["asset_geometry", "page_geometry"]

PORTRAIT_SIZE = (768, 1024)
SQUARE_SIZE = (1024, 1024)
LANDSCAPE_SIZE = (1344, 768)
ASPECT_TOLERANCE = 0.12

#: Style proof images are composed as a portrait 4:5 frame (the style-sample
#: prompt promises "Portrait 4:5 frame"). The generation dimensions must agree
#: with that promised composition, so style proof generation uses these
#: dimensions instead of the (default square) panel config dimensions.
# GPT Image 2.5 requires custom dimensions to be multiples of 16. This keeps
# the required 4:5 proof composition while remaining valid for every OpenAI
# image model Canary supports.
STYLE_PROOF_SIZE = (1024, 1280)
STYLE_PROOF_ASPECT = 0.8  # 4:5 portrait

#: Location design plates are composed as a wide landscape frame (the
#: location-plate prompt asks for a character-free location design plate). The
#: generation dimensions must agree with that promised composition.
LOCATION_PLATE_SIZE = (1344, 768)
LOCATION_PLATE_ASPECT = 1.75  # 16:9-ish wide plate (1344/768 = 1.75)


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
    actual_shape = generation_shape_for_aspect(actual_aspect)
    requested_shape = generation_shape_for_aspect(requested_aspect)
    if actual_shape == requested_shape:
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


# ---------------------------------------------------------------------------
# Asset-specific shapes (Slice 06 — geometry truth)
# ---------------------------------------------------------------------------

def style_proof_dimensions() -> tuple[int, int]:
    """Generation dimensions for a style proof image.

    The style-sample prompt promises a "Portrait 4:5 frame, filled edge to
    edge." The generation dimensions must agree with that composition instead
    of falling back to the (square) panel config dimensions, which produced a
    composition/dimension contradiction.
    """
    return STYLE_PROOF_SIZE


def location_plate_dimensions() -> tuple[int, int]:
    """Generation dimensions for a location design plate.

    Location design plates are landscape frames; the generation dimensions
    must agree with that wide composition. Routes
    that require specific provider sizes may remap in their transport layer,
    but the compiled/preview geometry reflects this verified wide shape.
    """
    return LOCATION_PLATE_SIZE


def aspect_matches_shape(
    aspect_ratio: float | None,
    shape: GenerationShape,
    *,
    tolerance: float = ASPECT_TOLERANCE,
) -> bool:
    """Validate a numeric aspect ratio against a generation shape, numerically.

    This is the 3:2-vs-16:9 guard: "landscape" alone is too coarse — a 3:2
    (1.5) and 16:9 (1.78) ratio are both "landscape" but represent different
    compositions. Returns True only when the ratio's own coarse shape matches
    ``shape`` AND the ratio is within ``tolerance`` of the shape's canonical
    aspect (so a 1.15 "landscape" is not accepted as a true wide frame).
    """
    if aspect_ratio is None or aspect_ratio <= 0:
        return False
    if generation_shape_for_aspect(aspect_ratio) != shape:
        return False
    return aspect_within_tolerance(
        aspect_ratio, _shape_canonical_aspect(shape), tolerance=tolerance
    )


def _shape_canonical_aspect(shape: GenerationShape) -> float:
    if shape == "portrait":
        return PORTRAIT_SIZE[0] / PORTRAIT_SIZE[1]
    if shape == "landscape":
        return LANDSCAPE_SIZE[0] / LANDSCAPE_SIZE[1]
    return 1.0
