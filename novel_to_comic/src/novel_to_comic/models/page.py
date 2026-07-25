"""Canonical semantic page contracts for the full-page pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.adaptation import LetteringItem, RevisionedArtifact


class PinnedGeometry(BaseModel):
    """Optional author-owned normalized bounds, never a planning default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _fits_page(self) -> "PinnedGeometry":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("pinned geometry must fit within the page")
        return self


class PageContent(BaseModel):
    """One ordered semantic unit of page content, not a panel render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    beat_ids: tuple[str, ...] = Field(min_length=1)
    visual_intent: str = Field(min_length=1)
    lettering: tuple[LetteringItem, ...] = ()
    entity_ids: tuple[str, ...] = ()
    appearance_state_ids: tuple[str, ...] = ()
    pinned_geometry: PinnedGeometry | None = None


class ComicPage(RevisionedArtifact):
    """The canonical publishable intent for one complete comic page."""

    page_number: int = Field(ge=1)
    adaptation_revision: int = Field(ge=1)
    adaptation_sha256: str = Field(min_length=64, max_length=64)
    page_turn_role: Literal[
        "none", "setup", "reveal", "cliffhanger", "release", "transition"
    ] = "none"
    spread_role: Literal["single", "left", "right", "spread"] = "single"
    emphasis: Literal[
        "establisher",
        "initial",
        "prolongation",
        "peak",
        "release",
        "transition",
    ]
    density_intent: Literal["sparse", "standard", "dense"]
    layout_intent: str = ""
    content: tuple[PageContent, ...] = Field(min_length=1)
    reading_order: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_page(self) -> "ComicPage":
        content_ids = [item.id for item in self.content]
        if len(content_ids) != len(set(content_ids)):
            raise ValueError("page content IDs must be unique")
        if [item.order for item in self.content] != list(
            range(1, len(self.content) + 1)
        ):
            raise ValueError("page content order must be consecutive")

        beat_ids = [beat_id for item in self.content for beat_id in item.beat_ids]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("adapted beats may appear only once on a page")

        lettering_ids = [
            lettering.id for item in self.content for lettering in item.lettering
        ]
        if len(lettering_ids) != len(set(lettering_ids)):
            raise ValueError("lettering IDs must be unique on a page")

        expected_order_ids = set(content_ids + lettering_ids)
        if len(self.reading_order) != len(set(self.reading_order)):
            raise ValueError("reading_order IDs must be unique")
        if set(self.reading_order) != expected_order_ids:
            raise ValueError(
                "reading_order must contain every page content and lettering ID"
            )
        return self


class PlannedPageRevision(BaseModel):
    """The page revision selected by the canonical book plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    revision: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)


class BookPlan(RevisionedArtifact):
    """The ordered manifest for Plan-owned canonical pages."""

    adaptation_revision: int = Field(ge=1)
    adaptation_sha256: str = Field(min_length=64, max_length=64)
    target_page_min: int = Field(ge=1)
    target_page_max: int = Field(ge=1)
    pages: tuple[PlannedPageRevision, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_plan(self) -> "BookPlan":
        if self.target_page_min > self.target_page_max:
            raise ValueError("target_page_min cannot exceed target_page_max")
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != list(range(1, len(self.pages) + 1)):
            raise ValueError("planned page numbers must be consecutive")
        if not self.target_page_min <= len(self.pages) <= self.target_page_max:
            raise ValueError("planned page count is outside the approved target range")
        return self
