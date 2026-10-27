"""Canonical semantic page contracts for the full-page pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.adaptation import LetteringItem, RevisionedArtifact
from novel_to_comic.models.validation import EditorialIssue


class ApprovedPageRange(BaseModel):
    """The human-approved target length; actual allocation may be shorter or longer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: int = Field(ge=1)
    maximum: int = Field(ge=1)
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
    label: str = ""
    continuity_guard: str = ""
    # Characters need per-panel acting; None means the kind is not known.
    # Objects are a scene's transient objects: written authority only.
    kind: Literal["character", "location", "prop", "object"] | None = None
    # Source-stated gender, age and unusual stature, sent beside the anchor so
    # the image model cannot drift a character's presentation or scale.
    identity: str = ""
    # Incidental source participants retain textual identity authority without
    # requiring a dedicated Cast sheet. Recurring/retained identities use images.
    requires_image: bool = True

    @model_validator(mode="after")
    def _written_character_authority(self) -> "ApprovedVisualReference":
        if not self.requires_image and self.kind not in {"character", "object"}:
            raise ValueError("Only incidental characters and scene objects may use written identity authority")
        if self.kind == "object" and self.requires_image:
            raise ValueError("Scene objects have written identity authority only")
        return self


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
        if self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9:
            raise ValueError("pinned geometry must fit within the page")
        return self


class NormalizedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class LetteringReservationIntent(BaseModel):
    """Coarse negative-space direction, not a typesetting/layout authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    preferred_zone: Literal["top-left", "top-center", "top-right", "middle-left",
                            "middle-right", "bottom-left", "bottom-center", "bottom-right"]
    footprint: Literal["compact", "standard", "wide", "tall"]
    line_budget: int = Field(ge=1, le=30)
    bounds: PinnedGeometry | None = None
    speaker_entity_id: str | None = None
    tail_target: NormalizedPoint | None = None


class LetteringReservation(LetteringReservationIntent):
    lettering_item_id: str = Field(min_length=1)


class AuthorGeometryPin(BaseModel):
    """An explicit author constraint attached to one adapted beat."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beat_id: str = Field(min_length=1)
    geometry: PinnedGeometry


class PanelCamera(BaseModel):
    """Per-panel camera direction; references never choose the shot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shot: Literal[
        "extreme_close_up", "close_up", "medium_close_up", "medium",
        "medium_wide", "wide", "extreme_wide", "insert",
    ]
    angle: Literal["eye_level", "low_angle", "high_angle", "overhead", "worms_eye", "dutch"]


class CharacterActing(BaseModel):
    """How one visible character performs in one panel.

    Left and right are the reader's screen directions. Identity comes from the
    Cast reference; facing, gaze and expression come from here, so a reference
    view never becomes the default pose or face.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(min_length=1)
    facing: Literal[
        "toward_viewer", "three_quarter_left", "three_quarter_right",
        "profile_left", "profile_right", "away_from_viewer",
    ]
    gaze: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    gesture: str = ""


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
    appearance_states: dict[str, str] = Field(default_factory=dict)
    pinned_geometry: PinnedGeometry | None = None
    # Plan requires both for new pages; validate_book_plan owns completeness.
    camera: PanelCamera | None = None
    acting: tuple[CharacterActing, ...] = ()

    @model_validator(mode="after")
    def _validate_references(self) -> "PageContent":
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("page-scoped entity IDs must be unique")
        if not set(self.appearance_states) <= set(self.entity_ids):
            raise ValueError("appearance states must belong to visible entities")
        acting_ids = [item.entity_id for item in self.acting]
        if len(acting_ids) != len(set(acting_ids)):
            raise ValueError("each visible character has at most one acting direction")
        if not set(acting_ids) <= set(self.entity_ids):
            raise ValueError("acting directions must belong to visible entities")
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
    # Absent on retained baked pages: omission preserves their original canonical
    # serialization/hash. New Plan responses always supply the complete tuple.
    lettering_reservations: tuple[LetteringReservation, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )

    @property
    def cited_beat_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(beat_id for item in self.content for beat_id in item.beat_ids))

    def cites_adaptation(self, adaptation) -> bool:
        """Planned from this adaptation, or from one amended since without touching its beats."""
        return adaptation.cites_current_beats(
            self.adaptation_revision, self.adaptation_sha256, self.cited_beat_ids)

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
        if self.lettering_reservations is not None:
            expected = [item.id for part in sorted(self.content, key=lambda c: c.order)
                        for item in part.lettering]
            if [r.lettering_item_id for r in self.lettering_reservations] != expected:
                raise ValueError("reservations must match every lettering ID exactly once in locked order")
            by_id = {item.id: (part, item) for part in self.content for item in part.lettering}
            for reservation in self.lettering_reservations:
                part, item = by_id[reservation.lettering_item_id]
                if reservation.speaker_entity_id is not None and (
                    reservation.speaker_entity_id not in part.entity_ids
                    or reservation.speaker_entity_id != item.speaker_entity_id
                    or item.delivery != "onscreen"
                ):
                    raise ValueError("reservation speaker must be the item's visible onscreen speaker")
                if reservation.tail_target is not None and reservation.speaker_entity_id is None:
                    raise ValueError("a tail target requires a visible speaker")
        return self


class PlannedPageRevision(BaseModel):
    """The page revision selected by the canonical book plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    revision: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)


class PlanReviewDraft(BaseModel):
    """Structurally valid pages awaiting a narrative decision, never Draw authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    adaptation_sha256: str = Field(min_length=64, max_length=64)
    rhythm_summary: str
    pages: tuple[ComicPage, ...] = Field(min_length=1)


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
        if any(issue.owner_stage != "plan" for issue in self.editorial_issues):
            raise ValueError("book-plan editorial issues must be owned by Plan")
        return self
