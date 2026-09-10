"""Complete-page Draw contracts and derived review records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.adaptation import LetteringItem, RevisionedArtifact
from novel_to_comic.models.page import ComicPage
from novel_to_comic.models.validation import EditorialIssue, InvariantFailure
from novel_to_comic.usage import UsageRecord


def _content_hash(model: BaseModel, field: str | None = None) -> str:
    payload = model.model_dump(
        mode="json",
        exclude={field} if field is not None else None,
    )
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
    output_media_type: Literal["image/png"] = "image/png"
    max_prompt_characters: int = Field(gt=0)
    retry_semantics: Literal["bounded_submission"]
    # Submission budget within one operation, never a lifetime page retry cap.
    # Draw currently submits once and surfaces failures for explicit recovery.
    max_attempts: int = Field(default=3, ge=1)
    price_per_page_usd: Decimal = Field(ge=0)
    price_per_reference_usd: Decimal = Field(default=Decimal("0"), ge=0)

    @property
    def content_sha256(self) -> str:
        return _content_hash(self)


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
    entity_id: str = Field(min_length=1)
    appearance_state_id: str | None = None
    label: str = ""
    continuity_guard: str = ""


class RetryProvenance(BaseModel):
    """Cumulative request lineage across explicit retries, not a submission budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: int = Field(ge=1)
    retries_request_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def _validate_retry(self) -> "RetryProvenance":
        if self.attempt == 1 and self.retries_request_sha256 is not None:
            raise ValueError("an initial request cannot cite retry lineage")
        if self.attempt > 1 and self.retries_request_sha256 is None:
            raise ValueError("a retry must cite the prior request identity")
        return self


class FrozenPageGenerationRequest(BaseModel):
    """Immutable provider request compiled from one ComicPage revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_sha256: str = ""
    page_number: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    edition_id: str = Field(min_length=1)
    edition_revision: int = Field(ge=1)
    edition_sha256: str = Field(min_length=64, max_length=64)
    profile_id: str = Field(min_length=1)
    profile_sha256: str = Field(min_length=64, max_length=64)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    lettering: tuple[LetteringItem, ...]
    references: tuple[PageReference, ...] = ()
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)
    output_media_type: Literal["image/png"]
    estimated_cost_usd: Decimal = Field(ge=0)
    artifact_kind: Literal["complete_page"] = "complete_page"
    retry: RetryProvenance
    correction: PageRenderCorrection | None = None

    @classmethod
    def compile(
        cls,
        *,
        page: ComicPage,
        edition: BookEdition,
        prompt: str,
        references: list[PageReference] | tuple[PageReference, ...],
        retry: RetryProvenance,
        correction: PageRenderCorrection | None = None,
    ) -> "FrozenPageGenerationRequest":
        profile = edition.capability_profile
        if len(prompt) > profile.max_prompt_characters:
            raise ValueError("prompt exceeds the selected capability profile")
        if len(references) > profile.max_image_references:
            raise ValueError("reference count exceeds the selected capability profile")
        return cls(
            page_number=page.page_number,
            comic_page_revision=page.revision,
            comic_page_sha256=page.content_sha256,
            edition_id=edition.id,
            edition_revision=edition.revision,
            edition_sha256=edition.content_sha256,
            profile_id=profile.id,
            profile_sha256=profile.content_sha256,
            provider=profile.provider,
            model=profile.model,
            prompt=prompt,
            lettering=[
                lettering for item in page.content for lettering in item.lettering
            ],
            references=references,
            output_width=profile.output_width,
            output_height=profile.output_height,
            output_media_type=profile.output_media_type,
            estimated_cost_usd=(
                profile.price_per_page_usd
                + profile.price_per_reference_usd * len(references)
            ),
            retry=retry,
            correction=correction,
        )

    @model_validator(mode="after")
    def _validate_request(self) -> "FrozenPageGenerationRequest":
        orders = [reference.order for reference in self.references]
        if orders != list(range(1, len(self.references) + 1)):
            raise ValueError("page references must have consecutive upload order")
        reference_ids = [reference.id for reference in self.references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("page reference IDs must be unique")
        if self.correction is not None and (
            self.correction.page_number != self.page_number
            or self.correction.comic_page_revision != self.comic_page_revision
            or self.correction.comic_page_sha256 != self.comic_page_sha256
        ):
            raise ValueError("correction lineage must match the frozen ComicPage")

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
    cost_usd: Decimal | None = Field(ge=0)

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


class CompletePageProviderResult(BaseModel):
    """One provider result whose production unit can only be a complete page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: Literal["complete_page"]
    image_bytes: bytes = Field(min_length=1)
    media_type: Literal["image/png"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    latency_ms: int = Field(ge=0)
    provider_request_id: str | None = None
    actual_provider_model: str | None = Field(min_length=1)
    usage: UsageRecord
    response_metadata: dict[str, object] | None = None


class PageGenerationProvenance(BaseModel):
    """Persisted billing and lineage record for one complete page render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    render: PageRenderRevision
    usage: UsageRecord
    provider_request_id: str | None = None
    response_metadata: dict[str, object] | None = None


class PageGenerationFailure(BaseModel):
    """Persisted explanation for the latest failed complete-page request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    request_sha256: str = Field(min_length=64, max_length=64)
    failed_at: datetime
    phase: Literal["generation", "analysis"] = "generation"
    classification: str = Field(min_length=1)
    recoverable: bool
    user_message: str = Field(min_length=1)
    error: str = Field(min_length=1)


class ObservedRegion(BaseModel):
    """Derived geometry detected in a render, never canonical layout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    polygon: tuple[tuple[float, float], ...] = Field(min_length=3)


class OCRTextObservation(BaseModel):
    """One ordered OCR observation from a complete page render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    detected_region_id: str | None = None
    role: Literal["comic_lettering", "incidental_text"] = "comic_lettering"


class OCRExtraction(BaseModel):
    """Deterministic adapter output; all geometry remains derived evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lettering: tuple[OCRTextObservation, ...] = ()
    incidental_text: tuple[OCRTextObservation, ...] = ()
    observed_regions: tuple[ObservedRegion, ...] = ()
    observed_reading_order: tuple[str, ...] = ()
    reading_order_proven: bool = False

    @model_validator(mode="after")
    def _validate_evidence_references(self) -> "OCRExtraction":
        observation_ids = [
            item.id for item in (*self.lettering, *self.incidental_text)
        ]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("OCR observation IDs must be unique")
        region_ids = [region.id for region in self.observed_regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("observed region IDs must be unique")
        known_regions = set(region_ids)
        if any(
            item.detected_region_id not in known_regions
            for item in (*self.lettering, *self.incidental_text)
            if item.detected_region_id is not None
        ):
            raise ValueError("OCR observation cites an unknown detected region")
        if len(self.observed_reading_order) != len(
            set(self.observed_reading_order)
        ):
            raise ValueError("observed reading-order IDs must be unique")
        if any(item not in known_regions for item in self.observed_reading_order):
            raise ValueError("observed reading order cites an unknown region")
        return self


class OCRProviderResponse(BaseModel):
    """Complete untyped OCR JSON retained before contract parsing."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = 1
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    request_sha256: str = Field(min_length=64, max_length=64)
    response: object
    raw_response: str | None = None
    parser_version: str = "page_ocr_v2"
    usage: UsageRecord


class RawOCRObservation(BaseModel):
    """Reusable provider observations, independent of the creative validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = 1
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    extraction: OCRExtraction
    usage: UsageRecord | None = None


class LetteringMatch(BaseModel):
    """Exact canonical-to-observed match evidence in page reading order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lettering_item_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    canonical_text: str = Field(min_length=1)
    observed_text: str = Field(min_length=1)


class RenderAnalysis(BaseModel):
    """Derived observations used to validate a complete page render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    validator_version: str = "legacy"
    comic_page_sha256: str = ""
    reading_order_proven: bool = False
    punctuation_policy: Literal["typographic_lettering_v2"] = "typographic_lettering_v2"
    recognized_lettering: dict[str, str] = Field(default_factory=dict)
    ocr_observations: tuple[OCRTextObservation, ...] = ()
    incidental_text: tuple[OCRTextObservation, ...] = ()
    lettering_matches: tuple[LetteringMatch, ...] = ()
    observed_regions: tuple[ObservedRegion, ...] = ()
    observed_reading_order: tuple[str, ...] = ()
    invariant_failures: tuple[InvariantFailure, ...] = ()
    editorial_issues: tuple[EditorialIssue, ...] = ()
    evidence: tuple[str, ...] = ()
    # Reading a page back is a second billable provider call. Its usage lives
    # here, on the artifact written only once that call succeeded, rather than
    # on generation provenance, which is recorded before the read happens.
    analysis_usage: UsageRecord | None = None

    @property
    def lettering_valid(self) -> bool:
        return not self.invariant_failures


class AnnotationPoint(BaseModel):
    """One normalized page-fraction coordinate, origin top-left, 0..1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class CorrectionAnnotation(BaseModel):
    """One normalized author mark on the page image plus its instruction.

    Points are normalized page fractions (origin top-left, 0..1), independent
    of render pixel size so marks survive across revisions. The note is always
    rendered into the provider prompt as a "Mark N" line; annotations are
    never stored without reaching the generation request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default="", max_length=120)
    kind: Literal["pin", "rectangle", "highlight", "freehand", "arrow", "ellipse", "text"]
    points: tuple[AnnotationPoint, ...] = Field(min_length=1, max_length=64)
    note: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _validate_mark(self) -> "CorrectionAnnotation":
        if self.kind in {"pin", "text"} and len(self.points) != 1:
            raise ValueError(f"{self.kind} annotation requires exactly one point")
        if self.kind in {"rectangle", "highlight", "ellipse", "arrow", "freehand"}:
            if len(self.points) < 2:
                raise ValueError(f"{self.kind} annotation requires at least two points")
            xs = [point.x for point in self.points]
            ys = [point.y for point in self.points]
            if max(xs) - min(xs) <= 1e-6 and max(ys) - min(ys) <= 1e-6:
                raise ValueError(f"{self.kind} annotation covers no page area")
        if not self.note.strip():
            raise ValueError("annotation note must not be blank")
        return self

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Bounding (x, y, width, height) page fractions covering every point."""
        xs = [point.x for point in self.points]
        ys = [point.y for point in self.points]
        x, y = min(xs), min(ys)
        return (x, y, max(xs) - x, max(ys) - y)

    def provider_guidance(self, index: int) -> str:
        """One provider-readable line grounding the note in page fractions."""
        tag = f" ({self.label})" if self.label else ""
        if self.kind == "pin":
            point = self.points[0]
            location = f"at x={point.x:.4f} y={point.y:.4f} of the page, origin top-left"
        else:
            x, y, width, height = self.bounds
            location = (
                f"x={x:.4f} y={y:.4f} w={width:.4f} h={height:.4f} "
                "of the page, origin top-left"
            )
        return f"Mark {index} [{self.kind}{tag} {location}]: {self.note.strip()}"


class CorrectionChange(BaseModel):
    """One author-editable change inside an explicit correction request.

    A change either edits the directive of an existing tracked issue
    (``issue_id``) or carries a manual instruction that becomes a real
    PageIssue on submission. The instruction is what reaches the provider;
    annotations ground it in normalized page geometry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=120)
    issue_id: str | None = Field(default=None, min_length=1)
    instruction: str = Field(min_length=1, max_length=1000)
    annotations: tuple[CorrectionAnnotation, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def _validate_change(self) -> "CorrectionChange":
        if not self.instruction.strip():
            raise ValueError("change instruction must not be blank")
        return self

class PageRenderCorrection(BaseModel):
    """One Draw-owned instruction whose output is still a complete page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_ids: tuple[str, ...] = Field(default=())
    page_number: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    parent_render_revision: int = Field(ge=1)
    parent_render_image_sha256: str = Field(min_length=64, max_length=64)
    mode: Literal["instructed", "region_targeted"]
    instruction: str = Field(min_length=1)
    detected_region_ids: tuple[str, ...] = ()
    resolved_regions: tuple[ObservedRegion, ...] = ()
    depiction: Literal["canonical", "less_graphic"] = "canonical"
    retained_instructions: tuple[str, ...] = ()
    changes: tuple[CorrectionChange, ...] = Field(default=(), max_length=24)
    note: str = Field(default="", max_length=1000)
    context_beat_ids: tuple[str, ...] = ()
    context_source_unit_ids: tuple[str, ...] = ()
    context_selected_source_unit_ids: tuple[str, ...] = ()
    context_adaptation_revision: int | None = Field(default=None, ge=1)
    context_adaptation_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    context_digest: str = ""
    context_truncated: bool = False
    artifact_kind: Literal["complete_page"] = "complete_page"

    @property
    def issue_id(self) -> str:
        return self.issue_ids[0]

    @model_validator(mode="after")
    def _validate_mode(self) -> "PageRenderCorrection":
        if not self.issue_ids and not self.changes and not self.note.strip():
            raise ValueError("correction requires selected issues, changes, or an author note")
        if len(set(self.issue_ids)) != len(self.issue_ids):
            raise ValueError("correction issue IDs must be unique")
        change_ids = [change.id for change in self.changes]
        if len(set(change_ids)) != len(change_ids):
            raise ValueError("correction change IDs must be unique")
        linked = [change.issue_id for change in self.changes if change.issue_id is not None]
        if len(set(linked)) != len(linked):
            raise ValueError("correction changes must link distinct issues")
        if set(linked) - set(self.issue_ids):
            raise ValueError("correction change links an issue outside the correction")
        if self.note and (not self.note.strip() or len(self.note) > 1000):
            raise ValueError("correction note must be blank or 1..1000 non-blank characters")
        total_annotations = sum(len(change.annotations) for change in self.changes)
        if total_annotations > 24:
            raise ValueError("correction carries at most 24 annotations")
        if len(set(self.context_beat_ids)) != len(self.context_beat_ids):
            raise ValueError("correction context beat IDs must be unique")
        if len(set(self.context_source_unit_ids)) != len(self.context_source_unit_ids):
            raise ValueError("correction context source unit IDs must be unique")
        if len(set(self.context_selected_source_unit_ids)) != len(self.context_selected_source_unit_ids):
            raise ValueError("correction selected source passages must be unique")
        if (self.context_adaptation_revision is None) != (self.context_adaptation_sha256 is None):
            raise ValueError("correction context lineage must be complete or absent")
        if self.mode == "region_targeted" and not self.detected_region_ids:
            raise ValueError("region-targeted correction requires a detected region")
        if self.mode == "instructed" and self.detected_region_ids:
            raise ValueError("instructed correction cannot carry detected regions")
        return self


class PageCorrectionIntent(BaseModel):
    """Validated routing decision before render lineage is attached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    parent_render_revision: int = Field(ge=1)
    mode: Literal["instructed", "region_targeted"]
    instruction: str = Field(min_length=1)
    detected_region_ids: tuple[str, ...] = ()
    artifact_kind: Literal["complete_page"] = "complete_page"


class AdaptCopyCorrectionRequest(BaseModel):
    """A wording request returned to Adapt; Draw never rewrites canonical copy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    owner_stage: Literal["adapt"] = "adapt"
    requested_change: str = Field(min_length=1)
    source_unit_ids: tuple[str, ...] = ()
    adapted_beat_ids: tuple[str, ...] = ()
    lettering_item_ids: tuple[str, ...] = ()
    requires_replan: Literal[True] = True


class PageIssueSummary(BaseModel):
    """Review-by-exception state; pages have no separate acceptance record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unresolved_issue_ids: tuple[str, ...] = ()
    blocking_issue_ids: tuple[str, ...] = ()
    accepted_editorial_issue_ids: tuple[str, ...] = ()

    @property
    def can_continue(self) -> bool:
        return not self.blocking_issue_ids


class PageIssue(BaseModel):
    """A review-by-exception concern attached to one page render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    issue_type: str = Field(min_length=1)
    classification: Literal["invariant_failure", "editorial_issue"] = (
        "editorial_issue"
    )
    correction_kind: Literal["render_fidelity", "copy_change"] = "render_fidelity"
    correction_owner: Literal["adapt", "draw"] = "draw"
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
    status: Literal["open", "revised", "accepted", "resolved", "dismissed"]
    resolution_revision: int | None = Field(default=None, ge=1)
    dismissal_reason: str | None = None

    @property
    def requires_resolution(self) -> bool:
        """Unproven OCR ordering is advisory, not an export approval gate."""
        return not (
            self.classification == "editorial_issue"
            and self.issue_type == "unverified_lettering_order"
        )

    @model_validator(mode="after")
    def _validate_resolution(self) -> "PageIssue":
        if self.classification == "invariant_failure" and self.status == "accepted":
            raise ValueError("an invariant failure cannot be deliberately accepted")
        if self.correction_owner == "adapt" and self.correction_kind != "copy_change":
            raise ValueError("only a copy change may be routed to Adapt")
        if self.correction_kind == "copy_change" and self.correction_owner != "adapt":
            raise ValueError("copy changes must be routed to Adapt")
        if self.status in {"resolved", "revised"} and self.resolution_revision is None:
            raise ValueError("resolved page issue requires a resolution revision")
        if self.status not in {"resolved", "revised"} and self.resolution_revision is not None:
            raise ValueError("only a resolved page issue has a resolution revision")
        if self.status == "dismissed" and not self.dismissal_reason:
            raise ValueError("dismissed page issue requires a reason")
        if self.status != "dismissed" and self.dismissal_reason is not None:
            raise ValueError("only a dismissed page issue has a dismissal reason")
        if (
            self.resolution_revision is not None
            and self.resolution_revision <= self.render_revision
        ):
            raise ValueError("resolution revision must follow the affected render")
        return self
