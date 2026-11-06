"""Typed access to the active full-page pipeline's canonical artifact tree."""

from __future__ import annotations

from novel_to_comic.artifact_lock import locked_mutation
from novel_to_comic.models.lettering import LetteringSettings, LetteringStyle, PageLettering

import base64
import re
import uuid
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from novel_to_comic.models.adaptation import AdaptationBrief, BookAdaptation
from novel_to_comic.models.cold_open import OpeningSnapshot
from novel_to_comic.models.crop_ocr import CropOCRReport
from novel_to_comic.models.textract_ocr import TextractAttempt, TextractPlan
from novel_to_comic.models.draw import (
    BookEdition,
    FrozenPageGenerationRequest,
    PageGenerationFailure,
    PageGenerationProvenance,
    PageRenderSelection,
    PageIssue,
    RenderAnalysis,
    RawOCRObservation,
    OCRProviderResponse,
)
from novel_to_comic.models.finish import FinishPreflight
from novel_to_comic.models.page import BookPlan, ComicPage, PlanReviewDraft
from novel_to_comic.models.parts import PartManifest, text_sha256
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.validation import StageValidation
from novel_to_comic.workspace import part_ordinal, series_root

if TYPE_CHECKING:
    from novel_to_comic.editorial import (
        StoredEditorialDecision,
    )


ArtifactModel = TypeVar("ArtifactModel", bound=BaseModel)


class ArtifactMissing(Exception):
    """Raised when the one canonical path for an artifact does not exist."""

    def __init__(self, name: str, path: Path) -> None:
        super().__init__(f"Artifact {name!r} not found: {path}")
        self.name = name
        self.path = path


_ARTIFACT_OWNER_STAGES = {
    "story_bible": "Extract",
    "cast_design": "Cast",
    "cast_review": "Cast",
    "source": "Extract",
    "opening_snapshot": "Extract",
    "part_manifest": "Extract",
    "adaptation_brief": "Brief",
    "book_adaptation": "Adapt",
    "failed_book_adaptation": "Adapt",
    "book_plan": "Plan",
    "comic_page": "Plan",
    "comic_page_revision": "Plan",
    "book_edition": "Draw",
    "page_generation_request": "Draw",
    "page_generation_provenance": "Draw",
    "render_analysis": "Draw",
    "textract_plan": "Draw",
    "textract_attempt": "Draw",
    "finish_preflight": "Finish",
}


class ArtifactInvalid(Exception):
    """Raised when a persisted artifact no longer satisfies its contract."""

    def __init__(self, name: str, path: Path, validation_error: ValidationError) -> None:
        label = name.replace("_", " ")
        owner_stage = _ARTIFACT_OWNER_STAGES.get(name)
        action = (
            f" Rerun {owner_stage} to rebuild it."
            if owner_stage is not None
            else ""
        )
        if name == "page_lettering":
            action = (" Rerun the stages in a new editable project to rebuild lettering; "
                      "this project’s revisions are retained.")
        super().__init__(
            f"Stored {label} is incompatible with the current pipeline.{action}"
        )
        self.name = name
        self.path = path
        self.validation_error = validation_error
        self.owner_stage = owner_stage


class TargetArtifacts:
    """The sole path and serialization boundary for target artifacts.

    ``project_dir`` is a part workspace (or a single-directory project). Page
    artifacts resolve against it; series-level artifacts (part manifest and
    texts, Cast design/review, the book lettering style) resolve against
    ``series_dir``. See ``workspace.py``.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.series_dir = series_root(self.project_dir)

    @property
    def cast_design_path(self) -> Path:
        return self.series_dir / "refs" / "cast_design.json"

    def read_cast_design(self):
        from novel_to_comic.cast_design import CastDesignPlan
        return self._read_model("cast_design", self.cast_design_path, CastDesignPlan)

    def write_cast_design(self, plan) -> None:
        self._write_model(self.cast_design_path, plan)

    @property
    def cast_review_path(self) -> Path:
        return self.series_dir / "refs" / "cast_review.json"

    def read_cast_review(self):
        from novel_to_comic.cast_design import CastVisualReview
        return self._read_model("cast_review", self.cast_review_path, CastVisualReview)

    def write_cast_review(self, review) -> None:
        self._write_model(self.cast_review_path, review)

    @property
    def cast_review_dismissals_path(self) -> Path:
        return self.series_dir / "refs" / "cast_review_dismissals.json"

    def read_cast_review_dismissals(self):
        from novel_to_comic.cast_design import CastReviewDismissals
        if not self.cast_review_dismissals_path.exists():
            return CastReviewDismissals(dismissed=[])
        return self._read_model("cast_review_dismissals", self.cast_review_dismissals_path,
                                CastReviewDismissals)

    def write_cast_review_dismissals(self, dismissals) -> None:
        self._write_model(self.cast_review_dismissals_path, dismissals)

    @property
    def cast_review_running_path(self) -> Path:
        """Marker present while a cast visual review call is in flight."""
        return self.series_dir / "refs" / ".cast_review_running"

    def archive_adaptation_work(self) -> Path:
        return self.archive_stage_work("adapt")

    def drawn_page_count(self) -> int:
        """Count retained art without requiring the old plan to deserialize."""
        return sum(1 for page in (self.project_dir / "draw" / "pages").glob("page_*")
                   if any(page.glob("render_*.png")))

    def restart_archives(self) -> list[dict]:
        """Read-only inventory; archived artifacts never become active inputs."""
        result = []
        for root in sorted((self.project_dir / ".checkpoints" / "restarts").glob("*"),
                           key=lambda path: path.stat().st_mtime, reverse=True):
            if root.is_symlink() or not root.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", root.name):
                continue
            files = sorted(str(path.relative_to(root)) for folder in ("draw", "finish", "exports")
                           for path in (root / folder).rglob("*")
                           if path.is_file() and not path.is_symlink()
                           and path.resolve().is_relative_to(root.resolve())
                           and path.suffix.lower() in {".png", ".webp", ".pdf", ".cbz"})
            result.append({"id": root.name, "created_at": root.stat().st_mtime,
                           "page_count": TargetArtifacts(root).drawn_page_count(), "files": files})
        return result

    def restart_archive_file(self, archive_id: str, relative: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", archive_id):
            raise ValueError("invalid archive identity")
        root = self.project_dir / ".checkpoints" / "restarts" / archive_id
        path = root / relative
        if (not Path(relative).parts or root.is_symlink()
                or Path(relative).parts[0] not in {"draw", "finish", "exports"}
                or any(part.startswith(".") for part in Path(relative).parts)
                or not path.resolve().is_relative_to(root.resolve())
                or path.suffix.lower() not in {".png", ".webp", ".pdf", ".cbz"}
                or not path.is_file()):
            raise ValueError("archived artwork not found")
        return path

    def archive_stage_work(self, stage: str) -> Path:
        """Start a new attempt while retaining outputs, checkpoints and budgets.

        The caller must admit the action and reserve credits first. Restore
        moved files if archiving fails; upstream inputs and editorial directives
        stay active. Archives are outside every generation checkpoint lookup.
        """
        from novel_to_comic.stages import clean_cascade

        if stage not in {"adapt", "plan"}:
            raise ValueError("only Adapt and Plan support archived restarts")

        archive = self.project_dir / ".checkpoints" / "restarts" / uuid4().hex
        archive.mkdir(parents=True)
        moved: list[tuple[Path, Path]] = []
        try:
            state_path = self.project_dir / "state.json"
            if state_path.exists():
                shutil.copy2(state_path, archive / "state.json")
            paths = [
                *clean_cascade(self.project_dir, stage),
                *(self.project_dir / ".checkpoints" / name
                  for name in (("adapt", "plan", "draw", "finish") if stage == "adapt" else ("plan", "draw", "finish"))),
            ]
            for source in paths:
                if not source.exists():
                    continue
                destination = archive / source.relative_to(self.project_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
                moved.append((source, destination))
        except BaseException:
            for source, destination in reversed(moved):
                destination.rename(source)
            shutil.rmtree(archive)
            raise
        return archive

    def narrative_review_path(self, phase: str) -> Path:
        if phase not in {"adapt", "plan", "plan_map"}:
            raise ValueError("unknown narrative review phase")
        return self.project_dir / ("adapt" if phase == "adapt" else "plan") / f"{phase}_review.json"

    def read_narrative_review(self, phase: str):
        from novel_to_comic.narrative_review import NarrativeReviewRecord
        return self._read_model("narrative_review", self.narrative_review_path(phase), NarrativeReviewRecord)

    def write_narrative_review(self, phase: str, review) -> None:
        self._write_model(self.narrative_review_path(phase), review)

    def generation_budget_path(self, stage: str, lineage: str) -> Path:
        if stage not in {"adapt", "plan"} or len(lineage) != 64 or any(c not in "0123456789abcdef" for c in lineage):
            raise ValueError("invalid generation budget identity")
        return self.project_dir / ".checkpoints" / stage / "work" / f"{lineage}.json"

    def read_generation_budget(self, stage: str, lineage: str):
        from novel_to_comic.generation_budget import GenerationBudget
        return self._read_model("generation_budget", self.generation_budget_path(stage, lineage), GenerationBudget)

    def write_generation_budget(self, stage: str, lineage: str, budget) -> None:
        self._write_model(self.generation_budget_path(stage, lineage), budget)

    @property
    def source_path(self) -> Path:
        return self.project_dir / "source" / "source.json"

    @property
    def part_manifest_path(self) -> Path:
        return self.series_dir / "source" / "parts.json"

    def part_text_path(self, identifier: str) -> Path:
        part_ordinal(identifier)
        return self.series_dir / "source" / "parts" / f"{identifier}.txt"

    def read_part_manifest(self) -> PartManifest:
        return self._read_model("part_manifest", self.part_manifest_path, PartManifest)

    def write_part_manifest(self, manifest: PartManifest) -> None:
        self._write_model(self.part_manifest_path, manifest)

    def read_part_text(self, identifier: str) -> str:
        """Return a part's exact source text, verified against its record."""

        record = self.read_part_manifest().get(identifier)
        path = self.part_text_path(identifier)
        if not path.exists():
            raise ArtifactMissing("part_text", path)
        text = path.read_text(encoding="utf-8")
        if text_sha256(text) != record.text_sha256:
            raise ValueError(f"source text for {identifier} changed outside Canary")
        return text

    def write_part_text(self, identifier: str, text: str) -> None:
        path = self.part_text_path(identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    @property
    def brief_path(self) -> Path:
        return self.project_dir / "brief" / "adaptation_brief.json"

    @property
    def adaptation_path(self) -> Path:
        return self.project_dir / "adapt" / "book.json"

    @property
    def failed_adaptation_candidate_path(self) -> Path:
        return self.project_dir / "adapt" / "failed_candidate.json"

    def adapt_checkpoint_path(self, name: str) -> Path:
        """Return a safe path for one resumable, non-canonical Adapt result."""

        if not name or any(part in {"", ".", ".."} for part in Path(name).parts):
            raise ValueError("adapt checkpoint name must be a safe relative path")
        path = Path(name)
        if path.is_absolute():
            raise ValueError("adapt checkpoint name must be relative")
        # Deliberately outside ``adapt/``: a normal stage retry clears canonical
        # Adapt outputs before running, while exact-input checkpoints must survive
        # that cleanup to avoid rebilling completed work.
        return (
            self.project_dir
            / ".checkpoints"
            / "adapt"
            / path.with_suffix(".json")
        )

    @property
    def plan_path(self) -> Path:
        return self.project_dir / "plan" / "book.json"

    @property
    def plan_review_draft_path(self) -> Path:
        return self.project_dir / "plan" / "review_draft.json"

    def write_plan_review_draft(self, draft: PlanReviewDraft) -> None:
        self._write_model(self.plan_review_draft_path, draft)

    def read_plan_review_draft(self) -> PlanReviewDraft:
        return self._read_model("plan_review_draft", self.plan_review_draft_path, PlanReviewDraft)

    def validation_path(self, stage: str) -> Path:
        if stage not in {"adapt", "plan"}:
            raise ValueError("only Adapt and Plan persist a stage validation artifact")
        return self.project_dir / stage / "validation.json"

    def page_path(self, page_number: int) -> Path:
        return self.project_dir / "plan" / "pages" / f"page_{page_number:03d}.json"

    def page_revision_path(self, page_number: int, revision: int) -> Path:
        return (
            self.project_dir
            / "plan"
            / "pages"
            / "revisions"
            / f"page_{page_number:03d}_rev_{revision:03d}.json"
        )

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

    def render_preview_path(
        self,
        page_number: int,
        render_revision: int,
        rendition: str,
    ) -> Path:
        if rendition not in {"thumbnail", "reader"}:
            raise ValueError(f"unknown page render rendition: {rendition}")
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / f"render_{render_revision:03d}.{rendition}.webp"
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

    def page_failure_path(self, page_number: int) -> Path:
        return (
            self.project_dir
            / "draw"
            / "pages"
            / f"page_{page_number:03d}"
            / "failure.json"
        )

    @property
    def preflight_path(self) -> Path:
        return self.project_dir / "finish" / "preflight.json"

    @property
    def exports_dir(self) -> Path:
        return self.project_dir / "exports"

    def normalized_page_path(self, page_number: int) -> Path:
        return self.project_dir / "finish" / "pages" / f"page_{page_number:03d}.jpg"

    def export_path(self, format: str) -> Path:
        if format not in {"pdf", "cbz"}:
            raise ValueError("target export format must be 'pdf' or 'cbz'")
        return self.exports_dir / f"comic.{format}"

    def provenance_revisions(self, page_number: int) -> tuple[int, ...]:
        page_dir = self.project_dir / "draw" / "pages" / f"page_{page_number:03d}"
        revisions: list[int] = []
        for path in page_dir.glob("provenance_*.json"):
            suffix = path.stem.removeprefix("provenance_")
            if suffix.isdigit():
                revisions.append(int(suffix))
        return tuple(sorted(revisions))

    def render_selection_path(self, page_number: int) -> Path:
        return self.provenance_path(page_number, 1).parent / "selection.json"

    def active_render_revision(self, page_number: int) -> int | None:
        path = self.render_selection_path(page_number)
        if path.exists():
            selected = self._read_model("page_render_selection", path, PageRenderSelection)
            render = self.read_provenance(page_number, selected.revision).render
            if render.image_sha256 != selected.image_sha256:
                raise ValueError("Selected artwork no longer matches its saved image. Select a version again.")
            return selected.revision
        revisions = self.provenance_revisions(page_number)
        return revisions[-1] if revisions else None

    @locked_mutation
    def select_render(self, page_number: int, revision: int, *, expected_revision: int) -> None:
        if self.active_render_revision(page_number) != expected_revision:
            raise ValueError("The selected version changed. Refresh and choose again.")
        render = self.read_provenance(page_number, revision).render
        if render.is_stale_for(self.read_page(page_number)):
            raise ValueError("This artwork belongs to an earlier page plan. Redraw the current page.")
        image = self.read_render(page_number, revision)
        if hashlib.sha256(image).hexdigest() != render.image_sha256:
            raise ValueError("Saved artwork does not match its provenance.")
        lineage: set[int] = set()
        ancestor = render
        while ancestor.revision not in lineage:
            lineage.add(ancestor.revision)
            if ancestor.parent_revision is None:
                break
            ancestor = self.read_provenance(page_number, ancestor.parent_revision).render
        try:
            issues = self.read_issues(page_number)
        except ArtifactMissing:
            issues = ()
        reopened = tuple(
            issue.model_copy(update={"status": "open", "resolution_revision": None})
            if issue.status in {"resolved", "revised"} and issue.resolution_revision not in lineage
            else issue
            for issue in issues
        )
        if reopened != issues:
            # A correction on another branch cannot verify the chosen artwork.
            self.write_issues(page_number, reopened)
        self._write_model(self.render_selection_path(page_number), PageRenderSelection(
            revision=revision, image_sha256=render.image_sha256,
        ))
        self.invalidate_finish()

    def request_revisions(self, page_number: int) -> tuple[int, ...]:
        page_dir = self.project_dir / "draw" / "pages" / f"page_{page_number:03d}"
        revisions: list[int] = []
        for path in page_dir.glob("request_*.json"):
            suffix = path.stem.removeprefix("request_")
            if suffix.isdigit():
                revisions.append(int(suffix))
        return tuple(sorted(revisions))

    def has_page_provenance(self) -> bool:
        return any(
            (self.project_dir / "draw" / "pages").glob(
                "page_*/provenance_*.json"
            )
        )

    def render_revisions(self, page_number: int) -> tuple[int, ...]:
        page_dir = self.project_dir / "draw" / "pages" / f"page_{page_number:03d}"
        revisions: list[int] = []
        for path in page_dir.glob("render_*.png"):
            suffix = path.stem.removeprefix("render_")
            if suffix.isdigit():
                revisions.append(int(suffix))
        return tuple(sorted(revisions))

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

    @property
    def opening_snapshot_path(self) -> Path:
        return self.project_dir / "source" / "opening.json"

    def write_opening_snapshot(self, snapshot: OpeningSnapshot) -> None:
        self._write_model(self.opening_snapshot_path, snapshot)

    def read_opening_snapshot(self) -> OpeningSnapshot:
        return self._read_model("opening_snapshot", self.opening_snapshot_path, OpeningSnapshot)

    def write_brief(self, brief: AdaptationBrief) -> None:
        self._write_model(self.brief_path, brief)

    def read_brief(self) -> AdaptationBrief:
        return self._read_model("adaptation_brief", self.brief_path, AdaptationBrief)

    @locked_mutation
    def invalidate_after_brief(self) -> None:
        """Remove target artifacts whose authority depends on Brief content."""

        for path in (
            self.project_dir / "adapt",
            self.project_dir / "plan",
            self.project_dir / "lettering",
            self.project_dir / "draw",
            self.project_dir / "finish",
            self.exports_dir,
        ):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

    @property
    def lettering_settings_path(self) -> Path:
        return self.project_dir / "lettering" / "settings.json"

    def read_lettering_settings(self) -> LetteringSettings:
        try:
            return self._read_model("lettering_settings", self.lettering_settings_path, LetteringSettings)
        except ArtifactMissing:
            return LetteringSettings(revision=1)

    @locked_mutation
    def write_lettering_settings(self, settings: LetteringSettings) -> None:
        history = self.project_dir / "lettering" / "revisions" / f"settings_{settings.revision:05d}_{settings.content_sha256}.json"
        self._write_immutable_model(history, settings, LetteringSettings)
        self._write_model(self.lettering_settings_path, settings)
        self.invalidate_finish()

    @locked_mutation
    def write_lettering_translation_evidence(self, attempt: str, name: str, payload: dict) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", attempt) or not re.fullmatch(r"[a-z0-9_-]+", name):
            raise ValueError("Invalid translation evidence identity")
        path = self.project_dir / "lettering" / "translations" / attempt / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @locked_mutation
    def publish_lettering_translation(self, states: list[PageLettering], style: LetteringStyle,
                                      settings: LetteringSettings) -> None:
        """Resolve before calling; roll back current pointers on ordinary write failure.

        Immutable revisions/evidence remain. Like other artifact publication this
        cannot promise crash atomicity across multiple filesystem replacements.
        """
        paths = [*(self.lettering_path(state.page_number) for state in states),
                 self.lettering_settings_path]
        if self.read_lettering_style().content_sha256 != style.content_sha256:
            raise ValueError("Book lettering style changed. Refresh the translation estimate.")
        previous = {path: path.read_bytes() if path.exists() else None for path in paths}
        try:
            for state in states:
                self.write_lettering(state)
            self.write_lettering_settings(settings)
        except Exception:
            for path, data in previous.items():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                    temporary.write_bytes(data)
                    os.replace(temporary, path)
            raise

    @property
    def lettering_style_path(self) -> Path:
        return self.series_dir / "lettering" / "style.json"

    def lettering_path(self, page_number: int) -> Path:
        if page_number < 1:
            raise ValueError("page number must be positive")
        return self.project_dir / "lettering" / "pages" / f"page_{page_number:03d}.json"

    def lettering_revision_path(self, state: PageLettering) -> Path:
        return self.project_dir / "lettering" / "revisions" / (
            f"page_{state.page_number:03d}_{state.revision:05d}_{state.content_sha256}.json"
        )

    def composite_path(self, page_number: int, identity: str, rendition: str = "full") -> Path:
        if page_number < 1 or not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("invalid composite identity")
        if rendition not in {"full", "reader", "thumbnail"}:
            raise ValueError("invalid composite rendition")
        suffix = "png" if rendition == "full" else "webp"
        return self.project_dir / "finish" / "composites" / f"page_{page_number:03d}_{identity}_{rendition}.{suffix}"

    def lettering_proof_path(self, identity: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("invalid lettering proof identity")
        return self.series_dir / "samples" / "lettering-proofs" / f"{identity}.png"

    @locked_mutation
    def write_lettering_proof(self, identity: str, data: bytes) -> Path:
        path = self.lettering_proof_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def read_lettering_style(self) -> LetteringStyle:
        return self._read_model("lettering_style", self.lettering_style_path, LetteringStyle)

    @locked_mutation
    def write_lettering_style(self, style: LetteringStyle) -> None:
        self._write_model(self.lettering_style_path, style)
        self.invalidate_finish()
        # The book style is series-wide: every part's packages used it.
        from novel_to_comic.workspace import part_workspaces

        for workspace in part_workspaces(self.series_dir):
            if workspace.resolve() != self.project_dir.resolve():
                TargetArtifacts(workspace).invalidate_finish()

    def read_lettering(self, page_number: int) -> PageLettering:
        return self._read_model("page_lettering", self.lettering_path(page_number), PageLettering)

    @locked_mutation
    def write_lettering(self, state: PageLettering) -> None:
        # Preserve each approved state for recovery; Draw regeneration never
        # deletes this tree. SHA filenames also survive page-number reuse.
        self._write_immutable_model(self.lettering_revision_path(state), state, PageLettering)
        self._write_model(self.lettering_path(state.page_number), state)
        self.invalidate_finish()

    @locked_mutation
    def write_composite(self, page_number: int, identity: str, data: bytes,
                        rendition: str = "full") -> Path:
        path = self.composite_path(page_number, identity, rendition)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return path

    @locked_mutation
    def invalidate_finish(self) -> None:
        """Discard a preflight and packages derived from superseded inputs.

        The persisted preflight is reused between browser sessions, so every
        mutation that can affect its verdict must invalidate it at the artifact
        boundary. Keeping this here avoids each page/issue route needing to
        remember the Book-stage cache.
        """

        for path in (self.project_dir / "finish", self.exports_dir):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

    @locked_mutation
    def write_adaptation(self, adaptation: BookAdaptation) -> None:
        self._write_model(self.adaptation_path, adaptation)
        self.invalidate_finish()

    def read_adaptation(self) -> BookAdaptation:
        return self._read_model("book_adaptation", self.adaptation_path, BookAdaptation)

    def write_failed_adaptation_candidate(self, adaptation: BookAdaptation) -> None:
        self._write_model(self.failed_adaptation_candidate_path, adaptation)

    def read_failed_adaptation_candidate(self) -> BookAdaptation:
        return self._read_model(
            "failed_book_adaptation",
            self.failed_adaptation_candidate_path,
            BookAdaptation,
        )

    def clear_failed_adaptation_candidate(self) -> None:
        self.failed_adaptation_candidate_path.unlink(missing_ok=True)

    def write_adapt_checkpoint(self, name: str, checkpoint: BaseModel) -> None:
        self._write_model(self.adapt_checkpoint_path(name), checkpoint)

    def adapt_repair_namespaces(self) -> tuple[str, ...]:
        """List repair batches, newest first, without reading their contents."""
        root = self.adapt_checkpoint_path("repairs/batch").parent
        if not root.exists():
            return ()
        directories = {path.parent for path in root.rglob("round_*.json")}
        return tuple(
            path.relative_to(root.parent).as_posix()
            for path in sorted(directories, key=lambda p: p.stat().st_mtime, reverse=True)
        )

    def read_adapt_checkpoint(
        self,
        name: str,
        model_type: type[ArtifactModel],
    ) -> ArtifactModel | None:
        path = self.adapt_checkpoint_path(name)
        if not path.exists():
            return None
        try:
            return model_type.model_validate_json(path.read_text())
        except ValidationError:
            # Checkpoints are disposable implementation details, not canonical
            # artifacts. An old shape is a cache miss, never a user-facing stage
            # failure.
            return None

    @locked_mutation
    def write_page(self, page: ComicPage) -> None:
        # The canonical path always holds the latest revision; each revision is
        # also archived so a render citing a superseded ComicPage revision stays
        # reconstructable after a copy correction replaces it. Re-planning the
        # same revision legitimately rewrites its archive entry, so this is not
        # an immutable write.
        self._write_model(
            self.page_revision_path(page.page_number, page.revision),
            page,
        )
        self._write_model(self.page_path(page.page_number), page)
        self.invalidate_finish()

    def read_page(self, page_number: int) -> ComicPage:
        return self._read_model("comic_page", self.page_path(page_number), ComicPage)

    def read_page_revision(self, page_number: int, revision: int) -> ComicPage:
        return self._read_model(
            "comic_page_revision",
            self.page_revision_path(page_number, revision),
            ComicPage,
        )

    def write_validation(self, validation: StageValidation) -> None:
        self._write_model(self.validation_path(validation.owner_stage), validation)

    def read_validation(self, stage: str) -> StageValidation:
        return self._read_model(
            f"{stage}_validation",
            self.validation_path(stage),
            StageValidation,
        )

    @locked_mutation
    def write_plan(self, plan: BookPlan) -> None:
        self._write_model(self.plan_path, plan)
        self.invalidate_finish()

    def read_plan(self) -> BookPlan:
        return self._read_model("book_plan", self.plan_path, BookPlan)

    @locked_mutation
    def write_book_edition(self, edition: BookEdition) -> None:
        self._write_immutable_model(self.book_edition_path, edition, BookEdition)
        self.invalidate_finish()

    def replace_book_edition(self, edition: BookEdition) -> None:
        """Advance the active edition while preserving prior request provenance."""

        current = self.read_book_edition()
        if edition.id != current.id or edition.revision != current.revision + 1:
            raise ValueError("replacement book edition must advance the current edition")
        self._write_model(self.book_edition_path, edition)
        self.invalidate_finish()

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
        return self._read_model(
            "page_generation_request", path, FrozenPageGenerationRequest
        )

    def producing_request(self, render) -> FrozenPageGenerationRequest:
        """The frozen request that produced one saved render."""
        for revision in reversed(self.request_revisions(render.page_number)):
            request = self.read_request(render.page_number, revision)
            if request.request_sha256 == render.request_sha256:
                return request
        raise ValueError("Saved render lacks its producing request")

    @locked_mutation
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
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(image)
        os.replace(temporary, path)
        self.invalidate_finish()

    def read_render(self, page_number: int, render_revision: int) -> bytes:
        path = self.render_path(page_number, render_revision)
        if not path.exists():
            raise ArtifactMissing("page_render", path)
        return path.read_bytes()

    @locked_mutation
    def write_provenance(self, provenance: PageGenerationProvenance) -> None:
        path = self.provenance_path(
            provenance.render.page_number,
            provenance.render.revision,
        )
        created = not path.exists()
        self._write_immutable_model(path, provenance, PageGenerationProvenance)
        if created:
            # New artwork becomes active; historical writes never reorder history.
            if provenance.render.revision == self.provenance_revisions(provenance.render.page_number)[-1]:
                self.render_selection_path(provenance.render.page_number).unlink(missing_ok=True)
            self.invalidate_finish()

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

    def persist_generated_page(
        self, provenance: PageGenerationProvenance, image: bytes
    ) -> None:
        """Journal the paid result as one atomic record before publishing its pair."""
        render = provenance.render
        if hashlib.sha256(image).hexdigest() != render.image_sha256:
            raise ValueError("generated image does not match provenance")
        path = self.provenance_path(render.page_number, render.revision).with_suffix(".pending")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "provenance": provenance.model_dump(mode="json"),
            "image": base64.b64encode(image).decode("ascii"),
        })
        if path.exists() and path.read_text() != payload:
            raise ValueError("occupied pending generation revision")
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("w") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        self.recover_generated_pages(render.page_number)

    def resumable_generation_request(
        self, page_number: int,
    ) -> FrozenPageGenerationRequest | None:
        """Return the frozen request for an unfinished paid generation action.

        The unfinished marker survives publication until successful completion
        (including settlement for queued jobs); completed artwork is not a retry.
        """
        pending = tuple(self.provenance_path(page_number, 1).parent.glob("provenance_*.pending"))
        if len(pending) > 1:
            raise ValueError("multiple pending generated pages require recovery before submission")
        if pending:
            payload = json.loads(pending[0].read_text())
            provenance = PageGenerationProvenance.model_validate(payload["provenance"])
        else:
            unfinished = tuple(
                self.provenance_path(page_number, 1).parent.glob("provenance_*.unfinished")
            )
            if not unfinished:
                return None
            if len(unfinished) > 1:
                raise ValueError("multiple unfinished generations require recovery before submission")
            revision = int(unfinished[0].stem.removeprefix("provenance_"))
            provenance = self.read_provenance(page_number, revision)
            if unfinished[0].read_text() != provenance.render.request_sha256:
                raise ValueError("unfinished generation identity does not match provenance")
        if provenance.render.page_number != page_number:
            raise ValueError("durable generation belongs to a different page")
        for revision in reversed(self.request_revisions(page_number)):
            request = self.read_request(page_number, revision)
            if request.request_sha256 == provenance.render.request_sha256:
                return request
        raise ValueError("durable paid generation lacks its frozen request; no image request allowed")

    def mark_generation_complete(self, provenance: PageGenerationProvenance) -> None:
        """Acknowledge operation success; queued jobs call this after settlement."""
        path = self.provenance_path(
            provenance.render.page_number, provenance.render.revision
        ).with_suffix(".unfinished")
        if path.exists() and path.read_text() != provenance.render.request_sha256:
            raise ValueError("unfinished generation identity does not match completion")
        path.unlink(missing_ok=True)

    def recover_generated_pages(self, page_number: int) -> tuple[PageGenerationProvenance, ...]:
        """Finish interrupted publication without contacting an image provider."""
        directory = self.provenance_path(page_number, 1).parent
        recovered: list[PageGenerationProvenance] = []
        for path in sorted(directory.glob("provenance_*.pending")):
            payload = json.loads(path.read_text())
            provenance = PageGenerationProvenance.model_validate(payload["provenance"])
            image = base64.b64decode(payload["image"], validate=True)
            render = provenance.render
            if render.page_number != page_number or hashlib.sha256(image).hexdigest() != render.image_sha256:
                raise ValueError("invalid pending generated page")
            self.write_render(page_number=page_number, render_revision=render.revision, image=image)
            self.write_provenance(provenance)
            unfinished = path.with_suffix(".unfinished")
            temporary = unfinished.with_name(f".{unfinished.name}.tmp")
            temporary.write_text(render.request_sha256)
            os.replace(temporary, unfinished)
            path.unlink()
            recovered.append(provenance)
        return tuple(recovered)

    def visual_review_path(self, page_number: int, render_revision: int, input_sha256: str) -> Path:
        return self.analysis_path(page_number, render_revision).parent / f"visual_{render_revision:03d}_{input_sha256}.json"

    def read_visual_reviews(self, page_number: int, render_revision: int):
        from novel_to_comic.page_visual_review import PageVisualReview
        directory = self.analysis_path(page_number, render_revision).parent
        return tuple(self._read_model("visual_review", path, PageVisualReview)
                     for path in sorted(directory.glob(f"visual_{render_revision:03d}_*.json")))

    def write_visual_review(self, report) -> None:
        from novel_to_comic.page_visual_review import PageVisualReview
        self._write_immutable_model(self.visual_review_path(report.page_number, report.render_revision, report.input_sha256), report, PageVisualReview)

    def read_visual_review(self, page_number: int, render_revision: int, input_sha256: str):
        from novel_to_comic.page_visual_review import PageVisualReview
        return self._read_model("visual_review", self.visual_review_path(page_number, render_revision, input_sha256), PageVisualReview)

    @locked_mutation
    def write_analysis(self, analysis: RenderAnalysis, *, provisional: bool = False) -> None:
        path = self.analysis_path(analysis.page_number, analysis.render_revision)
        if provisional:
            # Retryable evidence (an incomplete optional check) is current but
            # never becomes an immutable versioned record.
            self._write_model(path, analysis)
            self.invalidate_finish()
            return
        identity = hashlib.sha256(
            f"{analysis.validator_version}:{analysis.comic_page_sha256}".encode()
        ).hexdigest()
        versioned = path.with_name(f"{path.stem}_{identity}.json")
        self._write_immutable_model(versioned, analysis, RenderAnalysis)
        self._write_model(path, analysis)
        self.invalidate_finish()

    def read_analysis(
        self,
        page_number: int,
        render_revision: int,
    ) -> RenderAnalysis:
        path = self.analysis_path(page_number, render_revision)
        return self._read_model("render_analysis", path, RenderAnalysis)

    def ocr_response_path(self, page_number: int, render_revision: int) -> Path:
        return self.analysis_path(page_number, render_revision).with_name(
            f"ocr_response_{render_revision:03d}.json"
        )

    def write_ocr_response(self, response: OCRProviderResponse) -> None:
        self._write_immutable_model(
            self.ocr_response_path(response.page_number, response.render_revision),
            response, OCRProviderResponse,
        )

    def retire_unreadable_ocr_response(self, page_number: int, render_revision: int) -> None:
        """Keep an unreadable paid answer as evidence beside, not in place of, the next read."""
        path = self.ocr_response_path(page_number, render_revision)
        if not path.exists():
            return
        attempt = 1
        while (retired := path.with_name(f"{path.stem}.unreadable_{attempt}.json")).exists():
            attempt += 1
        path.rename(retired)

    def read_ocr_response(self, page_number: int, render_revision: int) -> OCRProviderResponse:
        return self._read_model(
            "ocr_response", self.ocr_response_path(page_number, render_revision),
            OCRProviderResponse,
        )

    def raw_ocr_path(self, page_number: int, render_revision: int) -> Path:
        return self.analysis_path(page_number, render_revision).with_name(
            f"ocr_{render_revision:03d}_v1.json"
        )

    def write_raw_ocr(self, observation: RawOCRObservation) -> None:
        self._write_immutable_model(
            self.raw_ocr_path(observation.page_number, observation.render_revision),
            observation, RawOCRObservation,
        )

    def read_raw_ocr(self, page_number: int, render_revision: int) -> RawOCRObservation:
        return self._read_model(
            "raw_ocr", self.raw_ocr_path(page_number, render_revision), RawOCRObservation
        )

    def crop_ocr_path(self, page_number: int, render_revision: int, input_sha256: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", input_sha256) is None:
            raise ValueError("Invalid crop OCR input hash")
        return self.analysis_path(page_number, render_revision).with_name(
            f"crop_ocr_{render_revision:03d}_{input_sha256}.json"
        )

    def write_crop_ocr(self, report: CropOCRReport) -> None:
        self._write_immutable_model(
            self.crop_ocr_path(report.page_number, report.render_revision, report.input_sha256),
            report, CropOCRReport,
        )

    def textract_path(self, page_number: int, revision: int, identity: str, name: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", identity) or not re.fullmatch(r"[a-z0-9_.]+", name):
            raise ValueError("Invalid hosted OCR artifact identity")
        return self.analysis_path(page_number, revision).parent / f"textract_{revision:03d}" / identity / name

    def read_textract_plan(self, page_number: int, revision: int, identity: str) -> TextractPlan:
        return self._read_model("textract_plan", self.textract_path(page_number, revision, identity, "plan.json"), TextractPlan)

    @locked_mutation
    def write_textract_plan(self, plan: TextractPlan) -> None:
        self._write_immutable_model(self.textract_path(plan.page_number, plan.render_revision, plan.input_sha256, "plan.json"), plan, TextractPlan)

    @locked_mutation
    def write_textract_crop(self, page_number: int, revision: int, identity: str, image: bytes) -> None:
        path = self.textract_path(page_number, revision, identity, "crop.png")
        if path.exists():
            if path.read_bytes() != image:
                raise ValueError("Hosted OCR crop identity collision")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(image)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def read_textract_crop(self, page_number: int, revision: int, identity: str) -> bytes:
        return self.textract_path(page_number, revision, identity, "crop.png").read_bytes()

    def textract_attempts(self, page_number: int, revision: int, identity: str) -> tuple[TextractAttempt, ...]:
        directory = self.textract_path(page_number, revision, identity, "crop.png").parent
        attempts = [self._read_model("textract_attempt", path, TextractAttempt)
                    for path in directory.glob("attempt_*.json")]
        return tuple(sorted(attempts, key=lambda item: (item.started_at, item.attempt_id)))

    @locked_mutation
    def write_textract_attempt(self, attempt: TextractAttempt) -> None:
        path = self.textract_path(attempt.page_number, attempt.render_revision,
                                  attempt.recognition_sha256, f"attempt_{attempt.attempt_id}.json")
        if path.exists():
            saved = self._read_model("textract_attempt", path, TextractAttempt)
            if saved.status == "succeeded" and saved != attempt:
                raise ValueError("Successful hosted OCR evidence is immutable")
        self._write_model(path, attempt)

    def read_crop_ocr(self, page_number: int, render_revision: int, input_sha256: str) -> CropOCRReport:
        return self._read_model(
            "crop_ocr", self.crop_ocr_path(page_number, render_revision, input_sha256), CropOCRReport,
        )

    @locked_mutation
    def write_issues(self, page_number: int, issues: tuple[PageIssue, ...]) -> None:
        path = self.issues_path(page_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            TypeAdapter(tuple[PageIssue, ...]).dump_json(issues, indent=2).decode()
        )
        self.invalidate_finish()

    def read_issues(self, page_number: int) -> tuple[PageIssue, ...]:
        path = self.issues_path(page_number)
        if not path.exists():
            raise ArtifactMissing("page_issues", path)
        return TypeAdapter(tuple[PageIssue, ...]).validate_json(path.read_text())

    def write_page_failure(self, failure: PageGenerationFailure) -> None:
        self._write_model(self.page_failure_path(failure.page_number), failure)

    def read_page_failure(self, page_number: int) -> PageGenerationFailure:
        path = self.page_failure_path(page_number)
        return self._read_model("page_generation_failure", path, PageGenerationFailure)

    def clear_page_failure(self, page_number: int) -> None:
        self.page_failure_path(page_number).unlink(missing_ok=True)

    @property
    def editorial_dir(self) -> Path:
        return self.project_dir / "editorial"

    @property
    def editorial_decisions_path(self) -> Path:
        return self.editorial_dir / "decisions.json"

    def read_editorial_decisions(self) -> tuple[StoredEditorialDecision, ...]:
        """Return revision-scoped keep/reopen records; absent means none."""

        from novel_to_comic.editorial import StoredEditorialDecision

        path = self.editorial_decisions_path
        if not path.exists():
            return ()
        try:
            return TypeAdapter(tuple[StoredEditorialDecision, ...]).validate_json(
                path.read_text()
            )
        except ValidationError as exc:
            raise ArtifactInvalid("editorial_decisions", path, exc) from exc
    def write_editorial_decisions(
        self, decisions: tuple[StoredEditorialDecision, ...] | list[StoredEditorialDecision]
    ) -> None:
        from novel_to_comic.editorial import StoredEditorialDecision

        path = self.editorial_decisions_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = TypeAdapter(
            tuple[StoredEditorialDecision, ...]
        ).dump_json(tuple(decisions), indent=2)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    @property
    def notes_dir(self) -> Path:
        # Outside adapt/ and plan/, which stage re-runs clear.
        return self.project_dir / "notes"

    def note_change_path(self, change_id: str) -> Path:
        if not re.fullmatch(r"note_[0-9a-f]{12}", change_id or ""):
            raise ValueError("note change id must look like note_<12 hex>")
        return self.notes_dir / f"{change_id}.json"

    def write_note_change(self, change) -> None:
        self._write_model(self.note_change_path(change.id), change)

    def read_note_change(self, change_id: str):
        from novel_to_comic.models.note_change import NoteChange

        return self._read_model("note_change", self.note_change_path(change_id), NoteChange)

    def list_note_changes(self) -> tuple:
        from novel_to_comic.models.note_change import NoteChange

        if not self.notes_dir.is_dir():
            return ()
        changes = [self._read_model("note_change", path, NoteChange)
                   for path in self.notes_dir.glob("note_*.json")]
        return tuple(sorted(changes, key=lambda change: (change.created_at, change.id)))

    def _note_snapshot_files(self) -> list[Path]:
        pages = sorted((self.project_dir / "plan" / "pages").glob("page_*.json"))
        return [self.adaptation_path, self.plan_path, *pages,
                self.narrative_review_path("adapt"), self.narrative_review_path("plan")]

    @locked_mutation
    def snapshot_for_note(self, change_id: str) -> None:
        """Copy the canonical Adapt and Plan files a carried note may rewrite."""

        snapshot = self.notes_dir / change_id
        if snapshot.exists():
            shutil.rmtree(snapshot)
        for path in self._note_snapshot_files():
            if path.exists():
                destination = snapshot / path.relative_to(self.project_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)

    @locked_mutation
    def restore_note_snapshot(self, change_id: str) -> None:
        """Put back exactly the files the snapshot held; archived page revisions stay."""

        snapshot = self.notes_dir / change_id
        if not snapshot.is_dir():
            raise ArtifactMissing("note_snapshot", snapshot)
        for path in self._note_snapshot_files():
            saved = snapshot / path.relative_to(self.project_dir)
            if saved.exists():
                shutil.copy2(saved, path)
            else:
                path.unlink(missing_ok=True)
        self.invalidate_finish()

    def write_preflight(self, preflight: FinishPreflight) -> None:
        self._write_model(self.preflight_path, preflight)

    def read_preflight(self) -> FinishPreflight:
        return self._read_model(
            "finish_preflight", self.preflight_path, FinishPreflight
        )

    @staticmethod
    def _write_model(path: Path, artifact: BaseModel) -> None:
        # Written through a temporary sibling: a crash mid-write would otherwise
        # leave a truncated canonical artifact that no stage can read.
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(artifact.model_dump_json(indent=2))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

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
        try:
            return model_type.model_validate_json(path.read_text())
        except ValidationError as exc:
            raise ArtifactInvalid(name, path, exc) from exc
