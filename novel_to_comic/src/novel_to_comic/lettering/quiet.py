"""How busy the base art is, per area; zero provider calls.

Seeds only. Edge density on a coarse grid tells walls, sky, floors and
shadow apart from faces, hands, props and pattern. Placement prefers the
quiet areas, the way a letterer looks for dead space; it knows nothing about
what the marks depict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageFilter

_COLUMNS = 96
_DETAIL_COLUMNS = 512  # Working width for edge detection.
_CEILING = 0.9  # Share of cells at or below which edge strength counts as fully busy.


@dataclass(frozen=True)
class BusyMap:
    columns: int
    rows: int
    integral: tuple[float, ...]  # (rows + 1) x (columns + 1) summed-area table of 0..1 busyness.

    def mean(self, x: float, y: float, width: float, height: float) -> float:
        """Mean busyness (0 quiet .. 1 busy) of a page-space rectangle."""
        left = max(0, min(self.columns - 1, int(x * self.columns)))
        right = max(left + 1, min(self.columns, math.ceil((x + width) * self.columns)))
        top = max(0, min(self.rows - 1, int(y * self.rows)))
        bottom = max(top + 1, min(self.rows, math.ceil((y + height) * self.rows)))
        if right <= left or bottom <= top:
            return 0.0
        stride = self.columns + 1
        table = self.integral
        total = (
            table[bottom * stride + right] - table[top * stride + right]
            - table[bottom * stride + left] + table[top * stride + left]
        )
        return total / ((right - left) * (bottom - top))


def busy_map(image: Image.Image) -> BusyMap:
    width, height = image.size
    columns = _COLUMNS
    rows = max(1, round(columns * height / max(1, width)))
    # Edges first at working size, then pooled: shrinking first would average
    # fine hatching and texture into flat tone and call it quiet.
    detail = max(columns, min(width, _DETAIL_COLUMNS))
    gray = image.convert("L").resize(
        (detail, max(1, round(detail * height / max(1, width)))), Image.Resampling.BOX,
    )
    edges = gray.filter(ImageFilter.FIND_EDGES).resize((columns, rows), Image.Resampling.BOX)
    values = list(edges.tobytes())  # One byte per cell in "L" mode.
    ceiling = sorted(values)[min(len(values) - 1, int(len(values) * _CEILING))] or 1
    stride = columns + 1
    integral = [0.0] * ((rows + 1) * stride)
    for row in range(rows):
        running = 0.0
        for column in range(columns):
            running += min(1.0, values[row * columns + column] / ceiling)
            integral[(row + 1) * stride + column + 1] = integral[row * stride + column + 1] + running
    return BusyMap(columns=columns, rows=rows, integral=tuple(integral))
