"""Independent, versioned post-production lettering. No raster-pixel authority."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from novel_to_comic.models.adaptation import RevisionedArtifact
from novel_to_comic.models.page import PinnedGeometry

Kind = Literal["caption", "dialogue", "thought", "sfx"]
Font = Literal[
    "ComicNeue-Bold",
    "EBGaramond-SemiBold",
    "Bangers-Regular",
    "MPLUS1p-Bold",
    "SpecialElite-Regular",
    "Exo2-SemiBold",
    "Creepster-Regular",
]
Color = str


class Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True
    )


class Point(Strict):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ReservationIntent(Strict):
    preferred_zone: Literal[
        "top_left",
        "top_center",
        "top_right",
        "bottom_left",
        "bottom_center",
        "bottom_right",
    ] = "top_left"
    footprint: Literal["compact", "standard", "wide", "tall"] = "standard"
    line_budget: int = Field(default=3, ge=1, le=30)
    bounds: PinnedGeometry | None = None
    tail_target: Point | None = None
    speaker_entity_id: str | None = None


class LetteringReservation(ReservationIntent):
    lettering_item_id: str = Field(min_length=1)
    panel: int = Field(ge=1)
    order: int = Field(ge=1)


class PageReservations(RevisionedArtifact):
    page_number: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    elements: tuple[LetteringReservation, ...] = ()


class RoleStyle(Strict):
    font: Font = "ComicNeue-Bold"
    # Sizes are design units per 1000 page-width units, never raster pixels.
    min_size: float = Field(default=13, ge=8, le=60)
    max_size: float = Field(default=22, ge=8, le=150)
    line_height: float = Field(default=1.12, ge=0.9, le=2)
    padding: float = Field(default=8, ge=0, le=40)
    align: Literal["left", "center", "right"] = "center"
    color: str = Field(default="#171717", pattern=r"^#[0-9a-fA-F]{6}$")
    fill: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    outline: str = Field(default="#171717", pattern=r"^#[0-9a-fA-F]{6}$")
    border: float = Field(default=1.6, ge=0, le=10)
    radius: float = Field(default=0, ge=0, le=40)
    letter_spacing: float = Field(default=0, ge=-1, le=8)
    stroke: float = Field(default=0, ge=0, le=8)

    @model_validator(mode="after")
    def size_range(self):
        if self.max_size < self.min_size:
            raise ValueError("maximum type size must be at least minimum type size")
        return self


class LetteringStyle(Strict):
    preset: Literal["literary", "noir", "manga", "vintage"] = "literary"
    direction: str = Field(default="", max_length=4000)
    caption: RoleStyle = RoleStyle(
        font="EBGaramond-SemiBold", align="left", fill="#fff9e9", max_size=22
    )
    dialogue: RoleStyle = RoleStyle()
    thought: RoleStyle = RoleStyle(fill="#fffdf8")
    sfx: RoleStyle = RoleStyle(
        font="Bangers-Regular",
        min_size=24,
        max_size=64,
        color="#fff9e9",
        stroke=1.8,
        border=0,
        padding=3,
    )


class ResolvedText(Strict):
    lines: tuple[str, ...] = ()
    widths: tuple[float, ...] = ()
    font_size: float = 0
    body_height: float = 0
    overflow: bool = False
    reason: str = ""
    signature: str = ""


class LetteringElementState(Strict):
    id: str = Field(min_length=1, max_length=120)
    source_lettering_item_id: str | None = None
    kind: Kind
    # Empty locale key is canonical-language display copy; no fake translation.
    copies: dict[str, str] = Field(default_factory=dict)
    suggested_placement: PinnedGeometry
    placement: PinnedGeometry
    tail_target: Point | None = None
    style_override: RoleStyle | None = None
    hidden: bool = False
    rotation: float = Field(default=0, ge=-45, le=45)
    scale: float = Field(default=1, ge=0.5, le=2)
    z_index: int = Field(default=0, ge=-100, le=100)
    resolved: ResolvedText = ResolvedText()

    @model_validator(mode="after")
    def bounded_copy(self):
        if len(self.copies) > 30 or any(
            len(k) > 35 or len(v) > 4000 for k, v in self.copies.items()
        ):
            raise ValueError(
                "lettering supports at most 30 locales and 4000 characters per element"
            )
        if self.kind not in {"dialogue", "thought"} and self.tail_target is not None:
            raise ValueError("only speech/thought elements can have tails")
        return self


class PageLettering(RevisionedArtifact):
    schema_version: Literal[1] = 1
    page_number: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    locale: str = Field(default="", max_length=35)
    style: LetteringStyle = LetteringStyle()
    elements: tuple[LetteringElementState, ...] = Field(default=(), max_length=100)
    reviewed_against_render_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [e.id for e in self.elements]
        source = [
            e.source_lettering_item_id
            for e in self.elements
            if e.source_lettering_item_id
        ]
        if len(set(ids)) != len(ids) or len(set(source)) != len(source):
            raise ValueError("lettering element and source IDs must be unique")
        return self
