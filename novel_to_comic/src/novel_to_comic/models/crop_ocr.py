"""Optional, blind close-up transcription evidence. Never visual acceptance."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CropOCRLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    # Pixel bounds in the submitted crop, in reading order.
    box: tuple[int, int, int, int]

    @model_validator(mode="after")
    def valid_bounds(self) -> CropOCRLine:
        left, top, right, bottom = self.box
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError("Crop text must have positive pixel bounds")
        return self


def assemble_crop_lines(fragments: tuple[CropOCRLine, ...]) -> tuple[CropOCRLine, ...]:
    """Join fragments on the same physical line before ordering the lines.

    Small top-edge differences between letters must not reorder a sentence.
    Scores remain conservative: each assembled line keeps its weakest fragment.
    """
    rows: list[list[CropOCRLine]] = []
    for fragment in sorted(
        fragments, key=lambda item: (item.box[1] + item.box[3], item.box[0])
    ):
        top, bottom = fragment.box[1], fragment.box[3]
        row = next(
            (
                row
                for row in rows
                if any(
                    min(bottom, item.box[3]) - max(top, item.box[1])
                    >= 0.5 * min(bottom - top, item.box[3] - item.box[1])
                    for item in row
                )
            ),
            None,
        )
        if row is None:
            rows.append([fragment])
        else:
            row.append(fragment)
    result = []
    for row in sorted(rows, key=lambda row: min(item.box[1] for item in row)):
        row.sort(key=lambda item: item.box[0])
        result.append(
            CropOCRLine(
                text=" ".join(item.text for item in row),
                confidence=min(item.confidence for item in row),
                box=(
                    min(item.box[0] for item in row),
                    min(item.box[1] for item in row),
                    max(item.box[2] for item in row),
                    max(item.box[3] for item in row),
                ),
            )
        )
    return tuple(result)


class CropOCRRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str
    status: Literal["read", "no_region", "over_budget", "unavailable"]
    crop_sha256: str | None = None
    bounds: tuple[int, int, int, int] | None = None
    lines: tuple[CropOCRLine, ...] = ()
    # The first read of this observation, kept beside the blind close-up read.
    primary_text: str
    verdict: Literal["agrees", "disagrees", "inconclusive"] = "inconclusive"

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


class CropOCRReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    input_sha256: str = Field(min_length=64, max_length=64)
    reader_fingerprint: str
    minimum_confidence: float = Field(ge=0, le=1)
    status: Literal["agrees", "disagrees", "inconclusive"]
    # False when a busy/failed worker or the time budget left reads undone.
    # Incomplete reports are never saved and are retried on revalidation.
    complete: bool = True
    readings: tuple[CropOCRRead, ...] = ()
