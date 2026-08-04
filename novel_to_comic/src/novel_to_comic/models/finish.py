"""Provider-free final preflight contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.validation import InvariantFailure, StageName


FINISH_PREFLIGHT_VALIDATOR_VERSION = 2


class PreflightDiagnostic(BaseModel):
    """Non-blocking implementation evidence retained for technical inspection.

    A diagnostic can be useful while hardening the pipeline without becoming an
    export blocker or asking an author to make a decision the product does not
    expose. It deliberately has no ``blocking`` or editorial disposition.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    owner_stage: StageName
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)


class PreflightPage(BaseModel):
    """The exact canonical page and render revision selected for export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    analysis_render_revision: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    trim_width: int | None = Field(default=None, gt=0)
    trim_height: int | None = Field(default=None, gt=0)
    bleed_px: int = Field(default=0, ge=0)
    color_profile: str | None = None
    normalized_image_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    invariant_failures: tuple[InvariantFailure, ...] = ()
    diagnostics: tuple[PreflightDiagnostic, ...] = ()
    unresolved_editorial_issue_ids: tuple[str, ...] = ()
    accepted_editorial_issue_ids: tuple[str, ...] = ()


class FinishProductionSpec(BaseModel):
    """Deterministic print properties; none authorize creative pixel repair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canvas_width: int = Field(gt=0)
    canvas_height: int = Field(gt=0)
    bleed_px: int = Field(default=0, ge=0)
    dpi: int = Field(default=300, gt=0)
    color_profile: Literal["sRGB"] = "sRGB"

    @model_validator(mode="after")
    def _validate_bleed(self) -> "FinishProductionSpec":
        if self.bleed_px * 2 >= min(self.canvas_width, self.canvas_height):
            raise ValueError("bleed must leave a positive trim area")
        return self

    @property
    def trim_width(self) -> int:
        return self.canvas_width - self.bleed_px * 2

    @property
    def trim_height(self) -> int:
        return self.canvas_height - self.bleed_px * 2


class DrawCorrectionRequest(BaseModel):
    """A provider-free handoff to Draw for one complete-page creative failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    owner_stage: Literal["draw"] = "draw"
    page_number: int = Field(ge=1)
    render_revision: int | None = Field(default=None, ge=1)
    failure_codes: tuple[str, ...] = Field(min_length=1)
    issue_ids: tuple[str, ...] = ()
    requested_correction: str = Field(min_length=1)
    artifact_kind: Literal["complete_page"] = "complete_page"


class ExportPackage(BaseModel):
    """Verified package identity and page order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["pdf", "cbz"]
    relative_path: str = Field(min_length=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(gt=0)
    page_numbers: tuple[int, ...] = Field(min_length=1)


class FinishPreflight(BaseModel):
    """Final, provider-free evidence for whether an edition can export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edition_revision: int = Field(ge=1)
    edition_sha256: str = Field(min_length=64, max_length=64)
    # Version 1 represents preflights persisted before continuity metadata was
    # made diagnostic-only. Book reloads those once, then retains version 2.
    validator_version: int = Field(default=1, ge=1)
    production: FinishProductionSpec | None = None
    pages: tuple[PreflightPage, ...] = Field(min_length=1)
    correction_requests: tuple[DrawCorrectionRequest, ...] = ()
    packages: tuple[ExportPackage, ...] = ()
    packaging_failures: tuple[InvariantFailure, ...] = ()

    @model_validator(mode="after")
    def _validate_page_order(self) -> "FinishPreflight":
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != list(range(1, len(self.pages) + 1)):
            raise ValueError("preflight page numbers must be consecutive")
        return self

    @property
    def ready_to_export(self) -> bool:
        return (
            not self.packaging_failures
            and not any(
                page.invariant_failures or page.unresolved_editorial_issue_ids
                for page in self.pages
            )
        )


class FinishResult(BaseModel):
    """The persisted preflight paired with verified exports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preflight: FinishPreflight
    packages: tuple[ExportPackage, ...] = ()
