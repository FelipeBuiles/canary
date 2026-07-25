"""Provider-free final preflight contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.models.validation import InvariantFailure


class PreflightPage(BaseModel):
    """The exact canonical page and render revision selected for export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    invariant_failures: tuple[InvariantFailure, ...] = ()
    unresolved_editorial_issue_ids: tuple[str, ...] = ()


class FinishPreflight(BaseModel):
    """Final, provider-free evidence for whether an edition can export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edition_revision: int = Field(ge=1)
    edition_sha256: str = Field(min_length=64, max_length=64)
    pages: tuple[PreflightPage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_page_order(self) -> "FinishPreflight":
        page_numbers = [page.page_number for page in self.pages]
        if page_numbers != list(range(1, len(self.pages) + 1)):
            raise ValueError("preflight page numbers must be consecutive")
        return self

    @property
    def ready_to_export(self) -> bool:
        return not any(page.invariant_failures for page in self.pages)
