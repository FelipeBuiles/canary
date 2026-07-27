"""Gateway-backed OCR for complete-page render analysis.

The adapter is deliberately blind to canonical lettering: it never receives the
words it is supposed to find. An OCR pass primed with the expected text cannot
falsify a render, and Draw's exact-lettering invariant would validate itself.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.config import Config
from novel_to_comic.models.draw import (
    ObservedRegion,
    OCRExtraction,
    OCRTextObservation,
)
from novel_to_comic.usage import ApiResult

PAGE_OCR_FEATURE = "draw.page_ocr"

_SYSTEM_PROMPT = (
    "You transcribe the visible lettering of a finished comic page exactly as "
    "drawn. You never translate, correct, complete, or reorder the words."
)

_INSTRUCTION = (
    "Transcribe every visible lettering element on this comic page: speech "
    "balloons, thought balloons, captions, and sound effects. Copy each one "
    "character for character, including punctuation and capitalisation as "
    "drawn. Join a balloon's line breaks with single spaces. Do not merge two "
    "balloons, do not split one balloon, and do not invent, complete, or "
    "correct wording. Report each element's normalized bounding box, where x "
    "and y are the top-left corner and all four values are between 0 and 1. "
    "Return only the JSON object."
)

# Two elements belong to the same reading row when their vertical centres are
# this close. Comic balloons in one tier sit at slightly different heights, so
# strict y-sorting would zig-zag across a row and invent order defects.
_ROW_BAND = 0.06


class _ObservedBox(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    def polygon(self) -> tuple[tuple[float, float], ...]:
        right = min(1.0, self.x + self.width)
        bottom = min(1.0, self.y + self.height)
        return (
            (self.x, self.y),
            (right, self.y),
            (right, bottom),
            (self.x, bottom),
        )


class _ObservedLettering(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    box: _ObservedBox


class _PageOCRDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lettering: tuple[_ObservedLettering, ...] = ()


def _reading_order(items: list[tuple[int, _ObservedLettering]]) -> list[int]:
    """Derive left-to-right, top-to-bottom order from detected geometry.

    The order comes from the boxes, not from the order the model happened to
    list them: geometry is the evidence Draw uses to decide whether a render
    genuinely contradicts canonical reading order.
    """

    by_row = sorted(items, key=lambda item: item[1].box.center[1])
    rows: list[list[tuple[int, _ObservedLettering]]] = []
    for entry in by_row:
        centre_y = entry[1].box.center[1]
        if rows and centre_y - rows[-1][0][1].box.center[1] <= _ROW_BAND:
            rows[-1].append(entry)
        else:
            rows.append([entry])
    ordered: list[int] = []
    for row in rows:
        ordered.extend(
            index for index, _ in sorted(row, key=lambda item: item[1].box.center[0])
        )
    return ordered


def build_extraction(draft: _PageOCRDraft) -> OCRExtraction:
    """Convert raw observations into derived evidence with stable IDs."""

    indexed = list(enumerate(draft.lettering, start=1))
    observations = tuple(
        OCRTextObservation(
            id=f"ocr_{index:03d}",
            text=item.text,
            detected_region_id=f"region_{index:03d}",
        )
        for index, item in indexed
    )
    regions = tuple(
        ObservedRegion(id=f"region_{index:03d}", polygon=item.box.polygon())
        for index, item in indexed
    )
    order = tuple(
        f"region_{index:03d}" for index in _reading_order(indexed)
    )
    return OCRExtraction(
        lettering=observations,
        observed_regions=regions,
        observed_reading_order=order,
    )


class GatewayPageOCRAdapter:
    """Read one complete page render through the configured vision model."""

    def __init__(self, config: Config, *, page_number: int) -> None:
        self._config = config
        self._page_number = page_number

    async def extract(self, image: bytes) -> ApiResult[OCRExtraction]:
        from novel_to_comic.clients.text import generate_json

        result = await generate_json(
            config=self._config,
            model=self._config.effective_page_ocr_model(),
            system_prompt=_SYSTEM_PROMPT,
            # The page number carries no canonical wording; it lets the
            # zero-cost replay service resolve which fixture page this is.
            user_content=f"{_INSTRUCTION}\ncanary_page_number: {self._page_number}",
            temperature=0.0,
            feature=PAGE_OCR_FEATURE,
            image_attachments=((image, "image/png"),),
        )
        return ApiResult(
            value=build_extraction(_PageOCRDraft.model_validate(result.value)),
            usage=result.usage,
        )
