"""Panel rectangles read from the gutters of base art; zero provider calls.

Draw composes each page freely, so Plan's content items are not panel
geometry. The gutters in the finished art are. This recursive XY cut finds
full-span light bands (gutters and page margins) and splits the page along
them. It observes borders only: it knows nothing about speakers, faces or empty
space, and art without light gutters yields one full-page panel.
"""

from __future__ import annotations

from PIL import Image

from novel_to_comic.models.page import PinnedGeometry

_LIGHT = 236  # Gutters are paper white; painted skies and voids rarely span a full row.
# Tinted paper (cream, newsprint) sits below paper white. A uniform page margin
# gives the paper's own tone; gutters are anything at least that light.
_MARGIN = 0.01  # Share of the shorter side sampled as the page margin.
_PAPER_TOLERANCE = 14
_PAPER_SPREAD = 16  # Wider margin spread means bleed art, not paper.
_PAPER_FLOOR = 180  # Dark margins are art or black gutters: keep paper white.
_FILL = 0.95  # Share of a row/column that must be light to count as gutter.
_MIN_PANEL = 0.06  # Ignore slivers narrower than this share of the page.
_MAX_DEPTH = 6


def _gutter_threshold(gray: Image.Image) -> int:
    """The lightness that counts as gutter: paper white, or the margin's paper tone."""
    width, height = gray.size
    band = max(2, int(min(width, height) * _MARGIN))
    margin = [
        *gray.crop((0, 0, width, band)).get_flattened_data(),
        *gray.crop((0, height - band, width, height)).get_flattened_data(),
        *gray.crop((0, band, band, height - band)).get_flattened_data(),
        *gray.crop((width - band, band, width, height - band)).get_flattened_data(),
    ]
    margin.sort()
    paper = margin[len(margin) // 2]
    spread = margin[3 * len(margin) // 4] - margin[len(margin) // 4]
    if spread > _PAPER_SPREAD or paper - _PAPER_TOLERANCE < _PAPER_FLOOR:
        return _LIGHT
    return min(_LIGHT, paper - _PAPER_TOLERANCE)


def detect_panels(image: Image.Image) -> tuple[PinnedGeometry, ...]:
    """Panel rectangles in normalized page space, in reading order.

    Reading order follows the cut tree: top-to-bottom tiers, then left-to-right
    within a tier (the left-to-right comic convention Plan uses).
    """
    gray = image.convert("L")
    width, height = gray.size
    if width < 16 or height < 16:
        return (PinnedGeometry(x=0, y=0, width=1, height=1),)
    light = _gutter_threshold(gray)
    mask = gray.point(lambda value: 255 if value >= light else 0)
    found: list[tuple[int, int, int, int]] = []

    def profile(box: tuple[int, int, int, int], horizontal: bool) -> list[float]:
        crop = mask.crop(box)
        size = (1, crop.height) if horizontal else (crop.width, 1)
        return [value / 255 for value in crop.resize(size, Image.Resampling.BOX).get_flattened_data()]

    def split(box, horizontal: bool, depth: int, retried: bool) -> None:
        x0, y0, x1, y1 = box
        segments: list[tuple[int, int]] = []
        start = None
        for index, share in enumerate([*profile(box, horizontal), 1.0]):
            if share < _FILL and start is None:
                start = index
            elif share >= _FILL and start is not None:
                segments.append((start, index))
                start = None
        minimum = (height if horizontal else width) * _MIN_PANEL
        segments = [(a, b) for a, b in segments if b - a >= minimum]
        if not segments:
            return
        for a, b in segments:
            sub = (x0, y0 + a, x1, y0 + b) if horizontal else (x0 + a, y0, x0 + b, y1)
            if len(segments) > 1:
                split(sub, not horizontal, depth + 1, False)
            elif retried or depth >= _MAX_DEPTH:
                found.append(sub)
            else:
                # One band: trim its margins, then try the other axis once.
                split(sub, not horizontal, depth + 1, True)

    split((0, 0, width, height), True, 0, False)
    if not found:
        return (PinnedGeometry(x=0, y=0, width=1, height=1),)
    return tuple(
        PinnedGeometry(
            x=x0 / width, y=y0 / height, width=(x1 - x0) / width, height=(y1 - y0) / height
        )
        for x0, y0, x1, y1 in found
    )
