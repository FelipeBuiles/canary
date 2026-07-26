"""Typed access to the full-page pipeline's canonical artifact tree.

This module is intentionally separate from the active legacy artifact helpers
until the atomic pipeline cutover.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from novel_to_comic.models.adaptation import AdaptationBrief, BookAdaptation
from novel_to_comic.models.draw import (
    BookEdition,
    FrozenPageGenerationRequest,
    PageGenerationProvenance,
    PageIssue,
    RenderAnalysis,
)
from novel_to_comic.models.finish import FinishPreflight
from novel_to_comic.models.page import BookPlan, ComicPage
from novel_to_comic.models.source import SourceDocument


ArtifactModel = TypeVar("ArtifactModel", bound=BaseModel)


class ArtifactMissing(Exception):
    """Raised when the one canonical path for an artifact does not exist."""

    def __init__(self, name: str, path: Path) -> None:
        super().__init__(f"Artifact {name!r} not found: {path}")
        self.name = name
        self.path = path


class TargetArtifacts:
    """The sole path and serialization boundary for target artifacts."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)

    @property
    def source_path(self) -> Path:
        return self.project_dir / "source" / "source.json"

    @property
    def brief_path(self) -> Path:
        return self.project_dir / "brief" / "adaptation_brief.json"

    @property
    def adaptation_path(self) -> Path:
        return self.project_dir / "adapt" / "book.json"

    @property
    def plan_path(self) -> Path:
        return self.project_dir / "plan" / "book.json"

    def page_path(self, page_number: int) -> Path:
        return self.project_dir / "plan" / "pages" / f"page_{page_number:03d}.json"

    @property
    def book_edition_path(self) -> Path:
        return self.project_dir / "draw" / "book_edition.json"

    def request_path(self, page_number: int, request_revision: int) -> Path:
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / f"request_{request_revision:03d}.json"
        )

    def render_path(self, page_number: int, render_revision: int) -> Path:
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / f"render_{render_revision:03d}.png"
        )

    def analysis_path(self, page_number: int, render_revision: int) -> Path:
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / f"analysis_{render_revision:03d}.json"
        )

    def provenance_path(self, page_number: int, render_revision: int) -> Path:
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / f"provenance_{render_revision:03d}.json"
        )

    def issues_path(self, page_number: int) -> Path:
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / "issues.json"
        )

    @property
    def preflight_path(self) -> Path:
        return self.project_dir / "finish" / "preflight.json"

    @property
    def exports_dir(self) -> Path:
        return self.project_dir / "exports"

    def write_source(self, source: SourceDocument) -> None:
        if self.source_path.exists():
            current = self.read_source()
            if (
                current.source_sha256 != source.source_sha256
                or current.units != source.units
            ):
                raise ValueError(
                    "immutable source text and source units cannot be overwritten"
                )
        self._write_model(self.source_path, source)

    def read_source(self) -> SourceDocument:
        return self._read_model("source", self.source_path, SourceDocument)

    def write_brief(self, brief: AdaptationBrief) -> None:
        self._write_model(self.brief_path, brief)

    def read_brief(self) -> AdaptationBrief:
        return self._read_model("adaptation_brief", self.brief_path, AdaptationBrief)

    def invalidate_after_brief(self) -> None:
        """Remove target artifacts whose authority depends on Brief content."""

        for path in (
            self.project_dir / "adapt",
            self.project_dir / "plan",
            self.project_dir / "draw",
            self.project_dir / "finish",
            self.exports_dir,
        ):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

    def write_adaptation(self, adaptation: BookAdaptation) -> None:
        self._write_model(self.adaptation_path, adaptation)

    def read_adaptation(self) -> BookAdaptation:
        return self._read_model("book_adaptation", self.adaptation_path, BookAdaptation)

    def write_page(self, page: ComicPage) -> None:
        self._write_model(self.page_path(page.page_number), page)

    def read_page(self, page_number: int) -> ComicPage:
        return self._read_model("comic_page", self.page_path(page_number), ComicPage)

    def write_plan(self, plan: BookPlan) -> None:
        self._write_model(self.plan_path, plan)

    def read_plan(self) -> BookPlan:
        return self._read_model("book_plan", self.plan_path, BookPlan)

    def write_book_edition(self, edition: BookEdition) -> None:
        self._write_immutable_model(self.book_edition_path, edition, BookEdition)

    def read_book_edition(self) -> BookEdition:
        return self._read_model("book_edition", self.book_edition_path, BookEdition)

    def write_request(
        self,
        request: FrozenPageGenerationRequest,
        *,
        request_revision: int,
    ) -> None:
        self._write_immutable_model(
            self.request_path(request.page_number, request_revision),
            request,
            FrozenPageGenerationRequest,
        )

    def read_request(
        self,
        page_number: int,
        request_revision: int,
    ) -> FrozenPageGenerationRequest:
        path = self.request_path(page_number, request_revision)
        return self._read_model("page_generation_request", path, FrozenPageGenerationRequest)

    def write_render(
        self,
        *,
        page_number: int,
        render_revision: int,
        image: bytes,
    ) -> None:
        if not image:
            raise ValueError("page render image cannot be empty")
        path = self.render_path(page_number, render_revision)
        if path.exists():
            if path.read_bytes() != image:
                raise ValueError("immutable page render cannot be overwritten")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)

    def read_render(self, page_number: int, render_revision: int) -> bytes:
        path = self.render_path(page_number, render_revision)
        if not path.exists():
            raise ArtifactMissing("page_render", path)
        return path.read_bytes()

    def write_provenance(self, provenance: PageGenerationProvenance) -> None:
        path = self.provenance_path(
            provenance.render.page_number,
            provenance.render.revision,
        )
        self._write_immutable_model(path, provenance, PageGenerationProvenance)

    def read_provenance(
        self,
        page_number: int,
        render_revision: int,
    ) -> PageGenerationProvenance:
        path = self.provenance_path(page_number, render_revision)
        return self._read_model(
            "page_generation_provenance",
            path,
            PageGenerationProvenance,
        )

    def write_analysis(self, analysis: RenderAnalysis) -> None:
        path = self.analysis_path(analysis.page_number, analysis.render_revision)
        self._write_model(path, analysis)

    def read_analysis(
        self,
        page_number: int,
        render_revision: int,
    ) -> RenderAnalysis:
        path = self.analysis_path(page_number, render_revision)
        return self._read_model("render_analysis", path, RenderAnalysis)

    def write_issues(self, page_number: int, issues: tuple[PageIssue, ...]) -> None:
        path = self.issues_path(page_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            TypeAdapter(tuple[PageIssue, ...]).dump_json(issues, indent=2).decode()
        )

    def read_issues(self, page_number: int) -> tuple[PageIssue, ...]:
        path = self.issues_path(page_number)
        if not path.exists():
            raise ArtifactMissing("page_issues", path)
        return TypeAdapter(tuple[PageIssue, ...]).validate_json(path.read_text())

    def write_preflight(self, preflight: FinishPreflight) -> None:
        self._write_model(self.preflight_path, preflight)

    def read_preflight(self) -> FinishPreflight:
        return self._read_model("finish_preflight", self.preflight_path, FinishPreflight)

    @staticmethod
    def _write_model(path: Path, artifact: BaseModel) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.model_dump_json(indent=2))

    @classmethod
    def _write_immutable_model(
        cls,
        path: Path,
        artifact: BaseModel,
        model_type: type[ArtifactModel],
    ) -> None:
        if path.exists():
            current = model_type.model_validate_json(path.read_text())
            if current != artifact:
                raise ValueError(f"immutable artifact cannot be overwritten: {path}")
            return
        cls._write_model(path, artifact)

    @staticmethod
    def _read_model(
        name: str,
        path: Path,
        model_type: type[ArtifactModel],
    ) -> ArtifactModel:
        if not path.exists():
            raise ArtifactMissing(name, path)
        return model_type.model_validate_json(path.read_text())
