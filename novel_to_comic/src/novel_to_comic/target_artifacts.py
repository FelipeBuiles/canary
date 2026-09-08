"""Typed access to the active full-page pipeline's canonical artifact tree."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from novel_to_comic.models.adaptation import AdaptationBrief, BookAdaptation
from novel_to_comic.models.draw import (
    BookEdition,
    FrozenPageGenerationRequest,
    PageGenerationFailure,
    PageGenerationProvenance,
    PageIssue,
    RenderAnalysis,
    RawOCRObservation,
)
from novel_to_comic.models.finish import FinishPreflight
from novel_to_comic.models.page import BookPlan, ComicPage
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.validation import StageValidation

if TYPE_CHECKING:
    from novel_to_comic.editorial import (
        StoredEditorialDecision,
        StoryChangeDirective,
        StoryChangeProposal,
    )


ArtifactModel = TypeVar("ArtifactModel", bound=BaseModel)


class ArtifactMissing(Exception):
    """Raised when the one canonical path for an artifact does not exist."""

    def __init__(self, name: str, path: Path) -> None:
        super().__init__(f"Artifact {name!r} not found: {path}")
        self.name = name
        self.path = path


_ARTIFACT_OWNER_STAGES = {
    "source": "Extract",
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
        super().__init__(
            f"Stored {label} is incompatible with the current pipeline.{action}"
        )
        self.name = name
        self.path = path
        self.validation_error = validation_error
        self.owner_stage = owner_stage


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

    def write_plan(self, plan: BookPlan) -> None:
        self._write_model(self.plan_path, plan)
        self.invalidate_finish()

    def read_plan(self) -> BookPlan:
        return self._read_model("book_plan", self.plan_path, BookPlan)

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

    def write_provenance(self, provenance: PageGenerationProvenance) -> None:
        path = self.provenance_path(
            provenance.render.page_number,
            provenance.render.revision,
        )
        created = not path.exists()
        self._write_immutable_model(path, provenance, PageGenerationProvenance)
        if created:
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

    def write_analysis(self, analysis: RenderAnalysis) -> None:
        path = self.analysis_path(analysis.page_number, analysis.render_revision)
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

    @property
    def story_changes_dir(self) -> Path:
        return self.project_dir / "story_changes"

    def story_change_path(self, proposal_id: str) -> Path:
        if (
            not proposal_id
            or proposal_id.strip() != proposal_id
            or any(
                part in {"", ".", ".."}
                for part in Path(proposal_id).parts
            )
            or Path(proposal_id).is_absolute()
            or not all(
                character.isalnum() or character in {"_", "-"}
                for character in proposal_id
            )
        ):
            raise ValueError("story-change proposal id must be a safe relative name")
        return self.story_changes_dir / f"proposal_{proposal_id}.json"

    def story_directive_path(self, stage: str) -> Path:
        if stage not in {"adapt", "plan"}:
            raise ValueError("story-change directive stage must be 'adapt' or 'plan'")
        return self.story_changes_dir / f"directive_{stage}.json"

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

    def write_story_change(self, proposal: StoryChangeProposal) -> None:
        from novel_to_comic.editorial import StoryChangeProposal

        self._write_model(self.story_change_path(proposal.id), proposal)

    def read_story_change(self, proposal_id: str) -> StoryChangeProposal:
        from novel_to_comic.editorial import StoryChangeProposal

        return self._read_model(
            "story_change", self.story_change_path(proposal_id), StoryChangeProposal
        )

    def list_story_changes(self) -> tuple[StoryChangeProposal, ...]:
        from novel_to_comic.editorial import StoryChangeProposal

        proposals: list[StoryChangeProposal] = []
        directory = self.story_changes_dir
        if directory.is_dir():
            for path in sorted(directory.glob("proposal_*.json")):
                proposals.append(
                    self._read_model("story_change", path, StoryChangeProposal)
                )
        proposals.sort(key=lambda proposal: (proposal.created_at, proposal.id))
        return tuple(proposals)

    def write_story_directive(self, directive: StoryChangeDirective) -> None:
        self._write_model(self.story_directive_path(directive.stage), directive)

    def peek_story_directive(self, stage: str) -> StoryChangeDirective | None:
        """Return the pending directive without consuming it.

        A file that exists but no longer parses raises instead of passing
        ``None`` back: callers would otherwise run a billed generation that
        silently ignores its approved instruction.
        """

        from novel_to_comic.editorial import StoryChangeDirective, StoryDirectiveError

        path = self.story_directive_path(stage)
        if not path.exists():
            return None
        try:
            return StoryChangeDirective.model_validate_json(path.read_text())
        except ValidationError as exc:
            raise StoryDirectiveError(
                f"stored {stage} story-change directive {path.name} is "
                "unreadable; apply the story change again to rewrite it "
                "before any generation runs"
            ) from exc

    def clear_story_directive(self, stage: str) -> None:
        self.story_directive_path(stage).unlink(missing_ok=True)

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
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(artifact.model_dump_json(indent=2))
        os.replace(temporary, path)

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
