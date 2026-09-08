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
    "Also return panels: a list of bounding boxes using x, y, width, height, "
    "only for clearly separated rectangular panels. Omit panels when borders "
    "or reading order are ambiguous. Return only the JSON object."
)



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
    panels: tuple[_ObservedBox, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def accept_bare_lettering_list(cls, value: Any) -> Any:
        """Accept the bare list Gemini sometimes emits despite the JSON prompt."""

        if isinstance(value, list):
            return {"lettering": value}
        return value


def _panel_order(panels: tuple[_ObservedBox, ...]) -> tuple[int, ...]:
    """Prove ordinary separated panel tiers, never a page-wide balloon sweep."""
    rows: list[list[int]] = []
    for index in sorted(range(len(panels)), key=lambda index: panels[index].y):
        panel = panels[index]
        if rows and panel.y < max(panels[i].y + panels[i].height for i in rows[-1]):
            row = rows[-1]
            # Staggered/overlapping tiers and inset panels need visual review.
            if any(abs(panel.y - panels[i].y) > 0.02
                   or abs(panel.y + panel.height - panels[i].y - panels[i].height) > 0.02
                   for i in row):
                return ()
            row.append(index)
        else:
            rows.append([index])
    ordered: list[int] = []
    for row in rows:
        row.sort(key=lambda index: panels[index].x)
        if any(panels[left].x + panels[left].width > panels[right].x
               for left, right in zip(row, row[1:])):
            return ()
        ordered.extend(row)
    return tuple(ordered)


def build_extraction(draft: _PageOCRDraft) -> OCRExtraction:
    """Convert raw observations into derived evidence with stable IDs."""

    indexed = list(enumerate(draft.lettering, start=1))
    panel_order = _panel_order(draft.panels)
    assignments: dict[int, int] = {}
    for index, item in indexed:
        containing = [
            panel_index for panel_index, panel in enumerate(draft.panels)
            if panel.x <= item.box.x and panel.y <= item.box.y
            and panel.x + panel.width >= item.box.x + item.box.width
            and panel.y + panel.height >= item.box.y + item.box.height
        ]
        if len(containing) == 1:
            assignments[index] = containing[0]
    proven = bool(panel_order) and all(
        index in assignments for index, item in indexed if item.role == "comic_lettering"
    )
    observations = tuple(
        OCRTextObservation(
            id=f"ocr_{index:03d}", text=item.text, role=item.role,
            detected_region_id=(
                f"panel_{assignments[index]:03d}" if proven and index in assignments
                else f"region_{index:03d}"
            ),
        )
        for index, item in indexed
    )
    regions = tuple(
        ObservedRegion(id=f"region_{index:03d}", polygon=item.box.polygon())
        for index, item in indexed
    ) + tuple(
        ObservedRegion(id=f"panel_{index:03d}", polygon=panel.polygon())
        for index, panel in enumerate(draft.panels)
    )
    return OCRExtraction(
        lettering=tuple(item for item in observations if item.role == "comic_lettering"),
        incidental_text=tuple(item for item in observations if item.role == "incidental_text"),
        observed_regions=regions,
        observed_reading_order=tuple(f"panel_{index:03d}" for index in panel_order) if proven else (),
        reading_order_proven=proven,
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
