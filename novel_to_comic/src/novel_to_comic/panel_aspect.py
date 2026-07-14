"""Canonical panel generation aspect helpers."""

from __future__ import annotations

import math
from typing import Literal

GenerationShape = Literal["portrait", "landscape", "square"]
GenerationAspectSource = Literal["page_geometry", "panel_shape", "shot_default"]

PORTRAIT_SIZE = (768, 1024)
SQUARE_SIZE = (1024, 1024)
LANDSCAPE_SIZE = (1344, 768)
ASPECT_TOLERANCE = 0.12

#: Style proof images are composed as a portrait 4:5 frame (the style-sample
#: prompt promises "Portrait 4:5 frame"). The generation dimensions must agree
#: with that promised composition, so style proof generation uses these
#: dimensions instead of the (default square) panel config dimensions.
STYLE_PROOF_SIZE = (819, 1024)
STYLE_PROOF_ASPECT = 0.8  # 4:5 portrait

#: Location design plates are composed as a wide landscape frame (the
#: location-plate prompt promises a "clean wide environment design plate"). The
#: generation dimensions must agree with that promised composition.
LOCATION_PLATE_SIZE = (1344, 768)
LOCATION_PLATE_ASPECT = 1.75  # 16:9-ish wide plate (1344/768 = 1.75)

# Reve's layout endpoints use a pixel coordinate frame rather than accepting a
# separate aspect-ratio parameter on render_layout.  The API requires supplied
# layout frames to use 32px multiples and keeps them in this area range.  The
# panel itself is still stored/rendered at the normal application dimensions;
# this is only the high-resolution coordinate frame for the layout contract.
REVE_LAYOUT_MIN_PIXELS = 3072 * 2560
REVE_LAYOUT_MAX_PIXELS = 4096 * 4096
REVE_LAYOUT_MAX_DIMENSION = 4096
REVE_LAYOUT_MIN_DIMENSION = 32


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


def dimensions_for_reve_layout(width: int | None, height: int | None) -> tuple[int, int]:
    """Return a valid Reve v2 layout coordinate frame for a target aspect.

    ``render_layout`` reads the output aspect from ``layout.width`` and
    ``layout.height``.  The frame therefore needs to preserve the panel's
    aspect while satisfying Reve's 32px-multiple and pixel-area constraints.
    Canary's panel shapes stay within the range where a 4096px long edge can
    satisfy those constraints without changing the intended composition.
    """
    aspect = aspect_for_dimensions(width, height) or 1.0
    # Extreme aspect ratios are not produced by the panel planner. Clamp them
    # to a layout-safe range rather than emitting a frame Reve will reject.
    aspect = min(2.0, max(0.5, aspect))

    if aspect >= 1.0:
        frame_width = REVE_LAYOUT_MAX_DIMENSION
        frame_height = round(frame_width / aspect / 32) * 32
    else:
        frame_height = REVE_LAYOUT_MAX_DIMENSION
        frame_width = round(frame_height * aspect / 32) * 32

    frame_width = max(REVE_LAYOUT_MIN_DIMENSION, min(REVE_LAYOUT_MAX_DIMENSION, frame_width))
    frame_height = max(REVE_LAYOUT_MIN_DIMENSION, min(REVE_LAYOUT_MAX_DIMENSION, frame_height))

    # The supported panel aspect range already clears the minimum. Keep this
    # guard for callers with unusual dimensions and make the fallback
    # deterministic if rounding ever puts a frame below Reve's lower bound.
    if frame_width * frame_height < REVE_LAYOUT_MIN_PIXELS:
        scale = math.sqrt(REVE_LAYOUT_MIN_PIXELS / (frame_width * frame_height))
        frame_width = min(REVE_LAYOUT_MAX_DIMENSION, round(frame_width * scale / 32) * 32)
        frame_height = min(REVE_LAYOUT_MAX_DIMENSION, round(frame_height * scale / 32) * 32)

    return frame_width, frame_height


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

    The location-plate prompt promises a "clean wide environment design plate."
    The generation dimensions must agree with that wide composition. Routes
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
