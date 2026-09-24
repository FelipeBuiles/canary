"""Gateway-backed OCR for complete-page render analysis.

The adapter is deliberately blind to canonical lettering: it never receives the
words it is supposed to find. An OCR pass primed with the expected text cannot
falsify a render, and Draw's exact-lettering invariant would validate itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.config import Config
from novel_to_comic.models.draw import (
    ObservedFigure,
    ObservedRegion,
    OCRExtraction,
    OCRTextObservation,
    OCRProviderResponse,
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
    "Return exactly the root object "
    '{"lettering":[{"text":"exact words","role":"comic_lettering",'
    '"box":{"x":0.0,"y":0.0,"width":0.1,"height":0.1}}],'
    '"panels":[{"x":0.0,"y":0.0,"width":1.0,"height":1.0}],'
    '"figures":[{"subject":"unknown","head":{"x":0.0,"y":0.0,"width":0.1,"height":0.1}}]}. '
    "The lettering list includes every visible text item and its role. "
    "Use empty arrays when no text, no unambiguous rectangular panels or no heads exist. "
    "Panel boxes use x, y, width, height directly, never a nested box. "
    "Figures list every clearly visible head of a person or creature; each head "
    "box covers hair to chin. "
    "Return only this JSON object, with no other root fields."
)

# The same look at the page also locates heads, so one call serves text checks
# and lettering placement. Portraits are labelled by opaque cast IDs, never by
# name or wording, so the text read stays blind to the script.
_SUBJECTS = (
    " After the page image come labelled cast portraits, in this order: {labels}. "
    "Set subject to a portrait's label only when that head is clearly the same "
    "character; otherwise use \"unknown\". Portraits are identity guides only: "
    "never report text, heads or panels from them."
)


@dataclass(frozen=True)
class CastPortrait:
    """A small approved portrait that lets the page read label heads."""

    entity_id: str
    image: bytes
    media_type: str = "image/png"



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


class _ObservedHead(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    subject: str = "unknown"
    head: _ObservedBox

    @model_validator(mode="before")
    @classmethod
    def accept_box_variants(cls, value: Any) -> Any:
        """Accept "box"/"box_2d" and [y_min, x_min, y_max, x_max] heads."""
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        box = normalized.pop("head", None) or normalized.pop("box", None) or normalized.pop("box_2d", None)
        if isinstance(box, (list, tuple)) and len(box) == 4:
            try:
                y_min, x_min, y_max, x_max = (float(item) for item in box)
            except (TypeError, ValueError):
                return value
            scale = 1000.0 if max(abs(float(item)) for item in box) > 1 else 1.0
            box = {"x": x_min / scale, "y": y_min / scale,
                   "width": (x_max - x_min) / scale, "height": (y_max - y_min) / scale}
        if isinstance(box, dict):
            box = {k: max(0.0, min(1.0, float(v))) if isinstance(v, (int, float)) else v for k, v in box.items()}
        normalized["head"] = box
        return normalized


class _PageOCRDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lettering: tuple[_ObservedLettering, ...]
    panels: tuple[_ObservedBox, ...] = ()
    figures: tuple[_ObservedHead, ...] = ()

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


def _figures(
    draft: _PageOCRDraft, subjects: frozenset[str] | None
) -> tuple[ObservedFigure, ...]:
    result = []
    for index, item in enumerate(draft.figures, start=1):
        box = item.head
        subject = item.subject.strip()
        known = subject if subject != "unknown" and (subjects is None or subject in subjects) else None
        result.append(ObservedFigure(
            id=f"figure_{index:03d}", entity_id=known, x=box.x, y=box.y,
            width=min(box.width, 1 - box.x) or box.width,
            height=min(box.height, 1 - box.y) or box.height,
        ))
    return tuple(result)


def build_extraction(
    draft: _PageOCRDraft, subjects: frozenset[str] | None = None
) -> OCRExtraction:
    """Convert raw observations into derived evidence with stable IDs.

    ``subjects`` are the portrait labels sent with the page; any other head
    label is dropped to "unknown". A replayed response without them keeps its
    labels as recorded.
    """

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
        figures=_figures(draft, subjects),
    )


class GatewayPageOCRAdapter:
    """Read one complete page render through the configured vision model."""

    def __init__(
        self, config: Config, *, page_number: int, portraits: tuple[CastPortrait, ...] = ()
    ) -> None:
        self._config = config
        self._page_number = page_number
        self._portraits = portraits
        self._artifacts = None
        self._render = None

    def bind_render(self, artifacts, render) -> None:
        """Attach the durable evidence sink without changing extract callers."""
        self._artifacts = artifacts
        self._render = render

    def _persist_response(self, result: ApiResult[str]) -> None:
        if self._artifacts is not None and self._render is not None:
            self._artifacts.write_ocr_response(OCRProviderResponse(
                page_number=self._page_number,
                render_revision=self._render.revision,
                render_image_sha256=self._render.image_sha256,
                request_sha256=self._render.request_sha256,
                response=None, raw_response=result.value, usage=result.usage,
            ))

    async def extract(self, image: bytes) -> ApiResult[OCRExtraction]:
        from novel_to_comic.clients.text import generate_json

        instruction = _INSTRUCTION
        if self._portraits:
            instruction += _SUBJECTS.format(
                labels=", ".join(p.entity_id for p in self._portraits)
            )
        result = await generate_json(
            config=self._config,
            model=self._config.effective_page_ocr_model(),
            system_prompt=_SYSTEM_PROMPT,
            # The page number carries no canonical wording; it lets the
            # zero-cost replay service resolve which fixture page this is.
            user_content=f"{instruction}\ncanary_page_number: {self._page_number}",
            temperature=0.0,
            feature=PAGE_OCR_FEATURE,
            json_schema=_PageOCRDraft.model_json_schema(),
            response_sink=self._persist_response,
            retry_invalid_json=False,
            image_attachments=(
                (image, "image/png"),
                *((p.image, p.media_type) for p in self._portraits),
            ),
        )
        return ApiResult(
            value=build_extraction(
                _PageOCRDraft.model_validate(result.value),
                frozenset(p.entity_id for p in self._portraits),
            ),
            usage=result.usage,
        )
