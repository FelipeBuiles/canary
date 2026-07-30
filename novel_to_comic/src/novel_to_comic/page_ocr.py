"""Gateway-backed OCR for complete-page render analysis.

The adapter is deliberately blind to canonical lettering: it never receives the
words it is supposed to find. An OCR pass primed with the expected text cannot
falsify a render, and Draw's exact-lettering invariant would validate itself.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.config import Config
from novel_to_comic.models.draw import (
    ObservedRegion,
    OCRExtraction,
    OCRTextObservation,
)
from novel_to_comic.usage import ApiResult

PAGE_OCR_FEATURE = "draw.page_ocr"

_SYSTEM_PROMPT = (
    "You identify and transcribe visible text on a finished comic page exactly "
    "as drawn. You distinguish publishable comic lettering from incidental "
    "in-world writing. You never translate, correct, complete, or reorder words."
)

_INSTRUCTION = (
    "Find visible text on this comic page. Assign role='comic_lettering' only "
    "to speech balloons, thought balloons, caption boxes, and sound effects. "
    "Assign role='incidental_text' to writing that exists inside the depicted "
    "world, including handwriting or print on notebooks, documents, books, "
    "newspapers, signs, labels, screens, clothing, and scenery. Copy each item "
    "character for character, including punctuation and capitalisation as "
    "drawn. Join a balloon's line breaks with single spaces. Do not merge two "
    "balloons, do not split one balloon, and do not invent, complete, or "
    "correct wording. Report each element's normalized bounding box, where x "
    "and y are the top-left corner and all four values are between 0 and 1. "
    "Use exactly this shape for every item: "
    '{"text":"exact words","role":"comic_lettering|incidental_text",'
    '"box":{"x":0.0,"y":0.0,"width":0.1,"height":0.1}}. '
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
    role: Literal["comic_lettering", "incidental_text"] = "comic_lettering"

    @model_validator(mode="before")
    @classmethod
    def accept_gemini_box_2d(cls, value: Any) -> Any:
        """Canonicalize common Gemini field and coordinate variants."""

        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "text" not in normalized and "text_content" in normalized:
            normalized["text"] = normalized.pop("text_content")
        for role_field in ("comic_lettering", "incidental_text"):
            role_value = normalized.get(role_field)
            if "text" not in normalized and isinstance(role_value, str):
                normalized["text"] = role_value
                normalized["role"] = role_field
            normalized.pop(role_field, None)

        coordinates = normalized.get("box")
        coordinate_field = "box"
        if not isinstance(coordinates, (list, tuple)):
            coordinates = normalized.get("box_2d")
            coordinate_field = "box_2d"
        if not isinstance(coordinates, (list, tuple)):
            return normalized
        if (
            isinstance(coordinates, (list, tuple))
            and len(coordinates) == 1
            and isinstance(coordinates[0], (list, tuple))
        ):
            coordinates = coordinates[0]
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 4:
            return value
        try:
            y_min, x_min, y_max, x_max = (float(item) for item in coordinates)
        except (TypeError, ValueError):
            return value
        scale = 1000.0 if max(abs(item) for item in coordinates) > 1 else 1.0
        return {
            key: item
            for key, item in normalized.items()
            if key not in {coordinate_field, "box_2d"}
        } | {
            "box": {
                "x": x_min / scale,
                "y": y_min / scale,
                "width": (x_max - x_min) / scale,
                "height": (y_max - y_min) / scale,
            }
        }


class _PageOCRDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lettering: tuple[_ObservedLettering, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def accept_bare_lettering_list(cls, value: Any) -> Any:
        """Accept the bare list Gemini sometimes emits despite the JSON prompt."""

        if isinstance(value, list):
            return {"lettering": value}
        return value


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
            role=item.role,
        )
        for index, item in indexed
    )
    regions = tuple(
        ObservedRegion(id=f"region_{index:03d}", polygon=item.box.polygon())
        for index, item in indexed
    )
    comic_items = [
        entry for entry in indexed if entry[1].role == "comic_lettering"
    ]
    order = tuple(f"region_{index:03d}" for index in _reading_order(comic_items))
    return OCRExtraction(
        lettering=tuple(
            item for item in observations if item.role == "comic_lettering"
        ),
        incidental_text=tuple(
            item for item in observations if item.role == "incidental_text"
        ),
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
