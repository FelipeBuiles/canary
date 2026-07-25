"""Complete-page Draw contracts and derived review records."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.adaptation import LetteringItem, RevisionedArtifact
from novel_to_comic.models.page import ComicPage


def _content_hash(model: BaseModel, field: str) -> str:
    payload = model.model_dump(mode="json", exclude={field})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PageCapabilityProfile(BaseModel):
    """Explicit capabilities and cost boundary for one page model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    complete_page_generation: Literal[True] = True
    exact_visible_lettering: Literal[True] = True
    max_image_references: int = Field(ge=0)
    reference_ordering: Literal["ordered"]
    editing_modes: tuple[Literal["instructed", "region_targeted"], ...] = ()
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)
    max_prompt_characters: int = Field(gt=0)
    retry_semantics: Literal["idempotent_request"]
    price_per_page_usd: Decimal = Field(ge=0)


class BookEdition(RevisionedArtifact):
    """One edition-wide page model selection; Draw never mixes providers."""

    id: str = Field(min_length=1)
    capability_profile: PageCapabilityProfile


class PageReference(BaseModel):
    """One approved page-scoped reference in provider upload order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    media_type: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    visual_anchor: str = Field(min_length=1)


class FrozenPageGenerationRequest(BaseModel):
    """Immutable provider request compiled from one ComicPage revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_sha256: str = ""
    page_number: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    profile_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    lettering: tuple[LetteringItem, ...]
    references: tuple[PageReference, ...] = ()
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)

    @classmethod
    def compile(
        cls,
        *,
        page: ComicPage,
        profile: PageCapabilityProfile,
        prompt: str,
        references: list[PageReference] | tuple[PageReference, ...],
    ) -> "FrozenPageGenerationRequest":
        if len(prompt) > profile.max_prompt_characters:
            raise ValueError("prompt exceeds the selected capability profile")
        if len(references) > profile.max_image_references:
            raise ValueError("reference count exceeds the selected capability profile")
        return cls(
            page_number=page.page_number,
            comic_page_revision=page.revision,
            comic_page_sha256=page.content_sha256,
            profile_id=profile.id,
            provider=profile.provider,
            model=profile.model,
            prompt=prompt,
            lettering=[
                lettering for item in page.content for lettering in item.lettering
            ],
            references=references,
            output_width=profile.output_width,
            output_height=profile.output_height,
        )

    @model_validator(mode="after")
    def _validate_request(self) -> "FrozenPageGenerationRequest":
        orders = [reference.order for reference in self.references]
        if orders != list(range(1, len(self.references) + 1)):
            raise ValueError("page references must have consecutive upload order")
        reference_ids = [reference.id for reference in self.references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("page reference IDs must be unique")

        digest = _content_hash(self, "request_sha256")
        if self.request_sha256 and self.request_sha256 != digest:
            raise ValueError("request_sha256 does not match frozen request content")
        object.__setattr__(self, "request_sha256", digest)
        return self

    def is_stale_for(self, page: ComicPage) -> bool:
        return (
            self.page_number != page.page_number
            or self.comic_page_revision != page.revision
            or self.comic_page_sha256 != page.content_sha256
        )


class PageRenderRevision(BaseModel):
    """One immutable complete-page image and its request lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    comic_page_revision: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    request_sha256: str = Field(min_length=64, max_length=64)
    image_sha256: str = Field(min_length=64, max_length=64)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    latency_ms: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _validate_lineage(self) -> "PageRenderRevision":
        if self.revision == 1 and self.parent_revision is not None:
            raise ValueError("initial page render cannot have a parent revision")
        if self.revision > 1 and self.parent_revision is None:
            raise ValueError("corrected page render requires a parent revision")
        if self.parent_revision is not None and self.parent_revision >= self.revision:
            raise ValueError("parent render revision must precede its child")
        return self

    def is_stale_for(self, page: ComicPage) -> bool:
        return (
            self.page_number != page.page_number
            or self.comic_page_revision != page.revision
            or self.comic_page_sha256 != page.content_sha256
        )


class ObservedRegion(BaseModel):
    """Derived geometry detected in a render, never canonical layout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    polygon: tuple[tuple[float, float], ...] = Field(min_length=3)


class RenderAnalysis(BaseModel):
    """Derived observations used to validate a complete page render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    recognized_lettering: dict[str, str] = Field(default_factory=dict)
    observed_regions: tuple[ObservedRegion, ...] = ()
    observed_reading_order: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


class PageIssue(BaseModel):
    """A review-by-exception concern attached to one page render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    issue_type: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    requested_correction: str = Field(min_length=1)
    source_unit_ids: tuple[str, ...] = ()
    adapted_beat_ids: tuple[str, ...] = ()
    lettering_item_ids: tuple[str, ...] = ()
    detected_region_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    appearance_state_ids: tuple[str, ...] = ()
    status: Literal["open", "accepted", "resolved"]
    resolution_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_resolution(self) -> "PageIssue":
        if self.status == "resolved" and self.resolution_revision is None:
            raise ValueError("resolved page issue requires a resolution revision")
        if self.status != "resolved" and self.resolution_revision is not None:
            raise ValueError("only a resolved page issue has a resolution revision")
        if (
            self.resolution_revision is not None
            and self.resolution_revision <= self.render_revision
        ):
            raise ValueError("resolution revision must follow the affected render")
        return self
