"""Canonical semantic page contracts for the full-page pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.adaptation import LetteringItem, RevisionedArtifact
from novel_to_comic.models.validation import EditorialIssue


class ApprovedPageRange(BaseModel):
    """The human-approved page-count bounds Plan must respect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: int = Field(ge=1)
    maximum: int = Field(ge=1)
    allow_expansion: bool = False
    approved: Literal[True] = True

    @model_validator(mode="after")
    def _validate_range(self) -> "ApprovedPageRange":
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class ApprovedVisualReference(BaseModel):
    """One Cast-approved visual authority available to page planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    appearance_state_id: str | None = None
    visual_anchor: str = Field(min_length=1)
    approved: Literal[True] = True


class ApprovedVisualReferenceInventory(BaseModel):
    """The complete approved entity and appearance-state inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    references: tuple[ApprovedVisualReference, ...] = ()

    @model_validator(mode="after")
    def _validate_inventory(self) -> "ApprovedVisualReferenceInventory":
        reference_ids = [reference.id for reference in self.references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("approved visual reference IDs must be unique")
        authority_keys = [
            (reference.entity_id, reference.appearance_state_id)
            for reference in self.references
        ]
        if len(authority_keys) != len(set(authority_keys)):
            raise ValueError(
                "each entity appearance state must have one approved reference"
            )
        return self


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


class AuthorGeometryPin(BaseModel):
    """An explicit author constraint attached to one adapted beat."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beat_id: str = Field(min_length=1)
    geometry: PinnedGeometry


class PageContent(BaseModel):
    """One planned semantic panel, never an independently generated asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    beat_ids: tuple[str, ...] = Field(min_length=1)
    panel_role: Literal[
        "establishing",
        "standard",
        "detail",
        "reaction",
        "action",
        "transition",
        "splash",
        "inset",
    ] = "standard"
    visual_intent: str = Field(min_length=1)
    lettering: tuple[LetteringItem, ...] = ()
    entity_ids: tuple[str, ...] = ()
    appearance_state_ids: tuple[str, ...] = ()
    pinned_geometry: PinnedGeometry | None = None

    @model_validator(mode="after")
    def _validate_references(self) -> "PageContent":
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("page-scoped entity IDs must be unique")
        if len(self.appearance_state_ids) != len(set(self.appearance_state_ids)):
            raise ValueError("page-scoped appearance-state IDs must be unique")
        return self


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
    rhythm_intent: str = ""
    layout_intent: str = ""
    content: tuple[PageContent, ...] = Field(min_length=1)
    reading_order: tuple[str, ...] = Field(min_length=1)

    def _compatible_content_hashes(self) -> tuple[str, ...]:
        """Accept the authored hash from before semantic panel roles existed."""

        if all("panel_role" in item.model_fields_set for item in self.content):
            return ()
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        for index, item in enumerate(self.content):
            if "panel_role" not in item.model_fields_set:
                payload["content"][index].pop("panel_role", None)
        return (self._content_digest(payload),)

    @model_validator(mode="after")
    def _validate_page(self) -> "ComicPage":
        content_ids = [item.id for item in self.content]
        if len(content_ids) != len(set(content_ids)):
            raise ValueError("page content IDs must be unique")
        if [item.order for item in self.content] != list(
            range(1, len(self.content) + 1)
        ):
            raise ValueError("page content order must be consecutive")

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
    rhythm_summary: str = ""
    pages: tuple[PlannedPageRevision, ...] = Field(min_length=1)
    editorial_issues: tuple[EditorialIssue, ...] = ()

    @model_validator(mode="after")
    def _validate_plan(self) -> "BookPlan":
        if self.target_page_min > self.target_page_max:
            raise ValueError("target_page_min cannot exceed target_page_max")
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != list(range(1, len(self.pages) + 1)):
            raise ValueError("planned page numbers must be consecutive")
        if not self.target_page_min <= len(self.pages) <= self.target_page_max:
            raise ValueError("planned page count is outside the approved target range")
        if any(issue.owner_stage != "plan" for issue in self.editorial_issues):
            raise ValueError("book-plan editorial issues must be owned by Plan")
        return self
