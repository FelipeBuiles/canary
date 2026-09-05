"""Provider-free final-book validation, normalization, and packaging."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from collections import defaultdict
from pathlib import Path

import img2pdf
from PIL import Image, ImageCms
from pypdf import PdfReader

from novel_to_comic.models.adaptation import BookAdaptation
from novel_to_comic.models.draw import PageIssue, PageRenderRevision, RenderAnalysis
from novel_to_comic.models.finish import (
    DrawCorrectionRequest,
    ExportPackage,
    FINISH_PREFLIGHT_VALIDATOR_VERSION,
    FinishPreflight,
    FinishProductionSpec,
    FinishResult,
    PreflightDiagnostic,
    PreflightPage,
)
from novel_to_comic.models.page import ComicPage
from novel_to_comic.models.validation import InvariantFailure
from novel_to_comic.page_review import normalize_ocr_punctuation
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts


_CREATIVE_FAILURES = {
    "corrupt_page_render",
    "page_render_dimensions",
    "render_lineage",
    "stale_page_render",
    "exact_ocr_status",
    "open_draw_invariant",
}


def _failure(
    *,
    page_number: int,
    owner_stage: str,
    code: str,
    message: str,
    artifact_ids: tuple[str, ...],
    evidence: tuple[str, ...],
) -> InvariantFailure:
    return InvariantFailure(
        id=f"finish-page-{page_number:03d}-{code}",
        owner_stage=owner_stage,
        code=code,
        message=message,
        artifact_ids=artifact_ids,
        evidence=evidence,
    )


def _diagnostic(
    *,
    page_number: int,
    owner_stage: str,
    code: str,
    message: str,
    artifact_ids: tuple[str, ...],
    evidence: tuple[str, ...],
) -> PreflightDiagnostic:
    return PreflightDiagnostic(
        id=f"finish-page-{page_number:03d}-{code}",
        owner_stage=owner_stage,
        code=code,
        message=message,
        artifact_ids=artifact_ids,
        evidence=evidence,
    )


def _canonical_lettering(page: ComicPage):
    by_id = {
        lettering.id: lettering
        for content in page.content
        for lettering in content.lettering
    }
    return tuple(by_id[item_id] for item_id in page.reading_order if item_id in by_id)


def _ocr_is_exact(
    page: ComicPage,
    render: PageRenderRevision,
    analysis: RenderAnalysis,
    *,
    dismissed_failure_ids: frozenset[str] = frozenset(),
) -> bool:
    canonical = _canonical_lettering(page)
    active_failures = tuple(
        failure
        for failure in analysis.invariant_failures
        if failure.id not in dismissed_failure_ids
    )
    if (
        analysis.page_number != page.page_number
        or analysis.render_revision != render.revision
        or analysis.render_image_sha256 != render.image_sha256
        or active_failures
    ):
        return False
    # A dismissed Draw finding is an explicit visual-review override of the
    # detector's OCR verdict. The analysis remains immutable evidence, but it
    # must not continue to block Finish after that decision.
    if analysis.invariant_failures:
        return True
    if len(analysis.lettering_matches) != len(canonical):
        return False
    for expected, match in zip(canonical, analysis.lettering_matches, strict=True):
        if (
            match.lettering_item_id != expected.id
            or normalize_ocr_punctuation(match.canonical_text)
            != normalize_ocr_punctuation(expected.text)
            or normalize_ocr_punctuation(match.observed_text)
            != normalize_ocr_punctuation(expected.text)
        ):
            return False
    return True


def _appearance_diagnostics(
    adaptation: BookAdaptation,
    pages: tuple[ComicPage, ...],
) -> dict[int, list[PreflightDiagnostic]]:
    """Check explicit state chronology before exporting the edition."""

    beats = {beat.id: beat for beat in adaptation.beats}
    active: dict[str, str] = {}
    activated: dict[str, set[str]] = defaultdict(set)
    seen_beats: set[str] = set()
    diagnostics: dict[int, list[PreflightDiagnostic]] = defaultdict(list)
    for page in pages:
        for content in page.content:
            for beat_id in content.beat_ids:
                beat = beats.get(beat_id)
                if beat is None or beat.id in seen_beats:
                    continue
                # Adjacent content items may decompose one adapted beat into
                # several visual moments. Apply its state changes once, not
                # once per content item.
                for change in beat.appearance_changes:
                    current = active.get(change.entity_id)
                    if (
                        change.from_state_id is not None
                        and current != change.from_state_id
                    ):
                        diagnostics[page.page_number].append(
                            _diagnostic(
                                page_number=page.page_number,
                                owner_stage="adapt",
                                code="cross_page_appearance_state",
                                message="Appearance-state chronology is inconsistent.",
                                artifact_ids=(
                                    beat.id,
                                    change.entity_id,
                                    change.to_state_id,
                                ),
                                evidence=(
                                    f"Expected prior state {change.from_state_id!r}; "
                                    f"found {current!r}.",
                                ),
                            )
                        )
                    active[change.entity_id] = change.to_state_id
                    activated[change.entity_id].add(change.to_state_id)
                seen_beats.add(beat.id)
            for entity_id in content.entity_ids:
                expected = active.get(entity_id)
                cited = ([content.appearance_states[entity_id]]
                         if entity_id in content.appearance_states else [])
                not_yet_activated = [
                    state_id
                    for state_id in cited
                    if state_id not in activated.get(entity_id, set())
                ]
                # A page may explicitly cite an earlier state for a timeline
                # or composite image. The invariant is that the state has
                # been activated and that a changed entity is not left
                # without any page-scoped state citation.
                if expected is not None and (not cited or not_yet_activated):
                    evidence = (
                        f"Active state for {entity_id!r} is {expected!r}; "
                        f"page content cites {cited!r}."
                    )
                    if not_yet_activated:
                        evidence = (
                            f"Page content cites states not yet activated for "
                            f"{entity_id!r}: {not_yet_activated!r}."
                        )
                    diagnostics[page.page_number].append(
                        _diagnostic(
                            page_number=page.page_number,
                            owner_stage="plan",
                            code="cross_page_appearance_state",
                            message="Page-scoped appearance state is stale across pages.",
                            artifact_ids=(content.id, entity_id, expected, *cited),
                            evidence=(evidence,),
                        )
                    )
    return diagnostics


def _load_active_render(
    artifacts: TargetArtifacts,
    page_number: int,
) -> tuple[PageRenderRevision | None, bytes | None, list[InvariantFailure]]:
    revisions = artifacts.provenance_revisions(page_number)
    if not revisions:
        return None, None, [
            _failure(
                page_number=page_number,
                owner_stage="draw",
                code="render_lineage",
                message="No complete-page render provenance exists.",
                artifact_ids=(f"page_{page_number:03d}",),
                evidence=("Finish requires one active complete-page Draw revision.",),
            )
        ]
    provenance_by_revision = {
        revision: artifacts.read_provenance(page_number, revision)
        for revision in revisions
    }
    provenance = provenance_by_revision[revisions[-1]]
    render = provenance.render
    failures: list[InvariantFailure] = []
    for revision, item in provenance_by_revision.items():
        if item.render.page_number != page_number or item.render.revision != revision:
            failures.append(
                _failure(
                    page_number=page_number,
                    owner_stage="draw",
                    code="render_lineage",
                    message="Render provenance is stored under the wrong page or revision.",
                    artifact_ids=(f"provenance_{revision:03d}",),
                    evidence=(
                        f"Stored render identifies page {item.render.page_number}, "
                        f"revision {item.render.revision}.",
                    ),
                )
            )
        parent = item.render.parent_revision
        if parent is not None and parent not in provenance_by_revision:
            failures.append(
                _failure(
                    page_number=page_number,
                    owner_stage="draw",
                    code="render_lineage",
                    message="Corrected render has a missing parent revision.",
                    artifact_ids=(f"render_{revision:03d}", f"render_{parent:03d}"),
                    evidence=(f"Revision {revision} cites absent parent {parent}.",),
                )
            )
    orphan_renders = sorted(
        set(artifacts.render_revisions(page_number)) - set(revisions)
    )
    if orphan_renders:
        failures.append(
            _failure(
                page_number=page_number,
                owner_stage="draw",
                code="render_lineage",
                message="Page render exists without generation provenance.",
                artifact_ids=tuple(
                    f"render_{revision:03d}" for revision in orphan_renders
                ),
                evidence=("Every complete-page render must retain Draw provenance.",),
            )
        )
    try:
        image = artifacts.read_render(page_number, render.revision)
    except ArtifactMissing:
        image = None
    if image is None or hashlib.sha256(image).hexdigest() != render.image_sha256:
        failures.append(
            _failure(
                page_number=page_number,
                owner_stage="draw",
                code="render_lineage",
                message="Page-render bytes do not match Draw provenance.",
                artifact_ids=(f"render_{render.revision:03d}",),
                evidence=(f"Expected image SHA-256 {render.image_sha256}.",),
            )
        )
    return render, image, failures


def _read_issues(
    artifacts: TargetArtifacts,
    page_number: int,
) -> tuple[PageIssue, ...]:
    try:
        return artifacts.read_issues(page_number)
    except ArtifactMissing:
        return ()


def _normalize_page(
    image: bytes,
    path: Path,
    production: FinishProductionSpec,
) -> str:
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    with Image.open(io.BytesIO(image)) as source:
        source.load()
        if source.size != (production.canvas_width, production.canvas_height):
            raise ValueError("page render dimensions do not match production canvas")
        if source.mode == "RGBA" and source.getextrema()[3] != (255, 255):
            raise ValueError("page render contains transparency")
        source_profile = source.info.get("icc_profile")
        if source_profile:
            normalized = ImageCms.profileToProfile(
                source.convert("RGB"),
                ImageCms.ImageCmsProfile(io.BytesIO(source_profile)),
                srgb,
                outputMode="RGB",
            )
        else:
            normalized = source.convert("RGB")
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized.save(
            path,
            "JPEG",
            icc_profile=srgb.tobytes(),
            dpi=(production.dpi, production.dpi),
            quality=production.jpeg_quality,
            # Comic inks and lettering are particularly susceptible to colour
            # bleeding from chroma subsampling. Retain 4:4:4 while still
            # removing PNG's much larger lossless payload.
            subsampling=0,
            optimize=True,
            progressive=True,
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _clear_derived_outputs(artifacts: TargetArtifacts) -> None:
    """Prevent stale or partial packages from surviving a new Finish attempt."""

    for format in ("pdf", "cbz"):
        path = artifacts.export_path(format)
        if path.exists():
            path.unlink()
    pages_dir = artifacts.project_dir / "finish" / "pages"
    if pages_dir.is_dir():
        for path in (*pages_dir.glob("page_*.png"), *pages_dir.glob("page_*.jpg")):
            path.unlink()


def _read_existing_preflight(
    artifacts: TargetArtifacts,
) -> FinishPreflight | None:
    try:
        return artifacts.read_preflight()
    except (ArtifactMissing, ValueError):
        return None


def _page_identity(preflight: FinishPreflight) -> tuple:
    return (
        preflight.edition_sha256,
        preflight.production,
        tuple(
            (
                page.page_number,
                page.comic_page_revision,
                page.comic_page_sha256,
                page.render_revision,
                page.render_image_sha256,
            )
            for page in preflight.pages
        ),
    )


def _safe_package_path(artifacts: TargetArtifacts, relative_path: str) -> Path | None:
    project_root = artifacts.project_dir.resolve()
    candidate = (artifacts.project_dir / relative_path).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError:
        return None
    return candidate


def _remove_packages(
    artifacts: TargetArtifacts,
    packages: tuple[ExportPackage, ...],
) -> None:
    for package in packages:
        path = _safe_package_path(artifacts, package.relative_path)
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def _reusable_packages(
    artifacts: TargetArtifacts,
    previous: FinishPreflight | None,
    current: FinishPreflight,
) -> tuple[ExportPackage, ...]:
    if previous is None or not previous.packages:
        return ()
    if _page_identity(previous) != _page_identity(current):
        _remove_packages(artifacts, previous.packages)
        return ()

    reusable: list[ExportPackage] = []
    for package in previous.packages:
        path = _safe_package_path(artifacts, package.relative_path)
        if path is None or not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if (
            len(data) == package.byte_size
            and hashlib.sha256(data).hexdigest() == package.content_sha256
        ):
            reusable.append(package)
    stale = tuple(package for package in previous.packages if package not in reusable)
    _remove_packages(artifacts, stale)
    return tuple(reusable)


def _package_exports(
    artifacts: TargetArtifacts,
    page_paths: tuple[Path, ...],
    formats: tuple[str, ...],
    production: FinishProductionSpec,
) -> tuple[ExportPackage, ...]:
    packages: list[ExportPackage] = []
    page_numbers = tuple(range(1, len(page_paths) + 1))
    for format in formats:
        output = artifacts.export_path(format)
        if format == "pdf":
            _atomic_write(output, img2pdf.convert([str(path) for path in page_paths]))
            pdf = PdfReader(output)
            if len(pdf.pages) != len(page_paths):
                raise ValueError("PDF page count does not match the active book")
            expected_width = production.canvas_width / production.dpi * 72
            expected_height = production.canvas_height / production.dpi * 72
            for page in pdf.pages:
                if (
                    abs(float(page.mediabox.width) - expected_width) > 0.02
                    or abs(float(page.mediabox.height) - expected_height) > 0.02
                ):
                    raise ValueError("PDF page dimensions do not match production")
        elif format == "cbz":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for page_number, path in zip(page_numbers, page_paths, strict=True):
                    archive.writestr(
                        f"page_{page_number:03d}.jpg",
                        path.read_bytes(),
                    )
            _atomic_write(output, buffer.getvalue())
            with zipfile.ZipFile(output) as archive:
                expected = [f"page_{number:03d}.jpg" for number in page_numbers]
                if archive.namelist() != expected or archive.testzip() is not None:
                    raise ValueError("CBZ order or archive integrity is invalid")
                for name in expected:
                    with Image.open(io.BytesIO(archive.read(name))) as image:
                        if image.format != "JPEG":
                            raise ValueError("CBZ pages must use optimized JPEG encoding")
                        if image.size != (
                            production.canvas_width,
                            production.canvas_height,
                        ):
                            raise ValueError(
                                "CBZ page dimensions do not match production"
                            )
                        if not image.info.get("icc_profile"):
                            raise ValueError("CBZ page is missing its color profile")
        else:
            raise ValueError(f"unsupported Finish export format {format!r}")
        data = output.read_bytes()
        packages.append(
            ExportPackage(
                format=format,
                relative_path=output.relative_to(artifacts.project_dir).as_posix(),
                content_sha256=hashlib.sha256(data).hexdigest(),
                byte_size=len(data),
                page_numbers=page_numbers,
            )
        )
    return tuple(packages)


def finish_book(
    artifacts: TargetArtifacts,
    *,
    production: FinishProductionSpec,
    formats: tuple[str, ...] = ("pdf", "cbz"),
    clear_derived_outputs: bool = True,
) -> FinishResult:
    """Preflight and export active complete pages without any provider seam."""

    previous_preflight = (
        _read_existing_preflight(artifacts)
        if not clear_derived_outputs and not formats
        else None
    )
    if clear_derived_outputs:
        _clear_derived_outputs(artifacts)
    plan = artifacts.read_plan()
    adaptation = artifacts.read_adaptation()
    edition = artifacts.read_book_edition()
    pages = tuple(artifacts.read_page(item.page_number) for item in plan.pages)
    appearance = _appearance_diagnostics(adaptation, pages)
    preflight_pages: list[PreflightPage] = []
    correction_requests: list[DrawCorrectionRequest] = []
    normalized_paths: list[Path] = []

    for selected, page in zip(plan.pages, pages, strict=True):
        diagnostics = []
        failures: list[InvariantFailure] = [
            _failure(page_number=page.page_number, owner_stage=item.owner_stage, code=item.code,
                     message=item.message, artifact_ids=item.artifact_ids, evidence=item.evidence)
            for item in appearance.get(page.page_number, ())
        ]
        issues = _read_issues(artifacts, selected.page_number)
        if (
            plan.adaptation_revision != adaptation.revision
            or plan.adaptation_sha256 != adaptation.content_sha256
        ):
            failures.append(
                _failure(
                    page_number=selected.page_number,
                    owner_stage="plan",
                    code="adaptation_lineage",
                    message="BookPlan is stale for the canonical BookAdaptation.",
                    artifact_ids=("adapt/book.json", "plan/book.json"),
                    evidence=(
                        f"Plan cites adaptation revision {plan.adaptation_revision} "
                        f"and hash {plan.adaptation_sha256}.",
                    ),
                )
            )
        if (
            page.adaptation_revision != adaptation.revision
            or page.adaptation_sha256 != adaptation.content_sha256
        ):
            failures.append(
                _failure(
                    page_number=selected.page_number,
                    owner_stage="plan",
                    code="adaptation_lineage",
                    message="ComicPage is stale for the canonical BookAdaptation.",
                    artifact_ids=(f"page_{selected.page_number:03d}",),
                    evidence=(
                        f"ComicPage cites adaptation revision "
                        f"{page.adaptation_revision} and hash "
                        f"{page.adaptation_sha256}.",
                    ),
                )
            )
        if (
            selected.page_number != page.page_number
            or selected.revision != page.revision
            or selected.content_sha256 != page.content_sha256
        ):
            failures.append(
                _failure(
                    page_number=selected.page_number,
                    owner_stage="plan",
                    code="active_page_order",
                    message="The active BookPlan does not select this ComicPage revision.",
                    artifact_ids=(f"page_{selected.page_number:03d}",),
                    evidence=(
                        f"Plan selects revision {selected.revision} "
                        f"with hash {selected.content_sha256}.",
                    ),
                )
            )
        render, image, render_failures = _load_active_render(
            artifacts,
            selected.page_number,
        )
        failures.extend(render_failures)
        analysis: RenderAnalysis | None = None
        if render is not None:
            if render.provider != edition.capability_profile.provider or render.model != edition.capability_profile.model:
                failures.append(_failure(
                    page_number=page.page_number, owner_stage="draw", code="edition_model_mismatch",
                    message="This render belongs to a different page model; regenerate the edition.",
                    artifact_ids=(f"render_{render.revision:03d}",),
                    evidence=(f"Render model={render.model}; edition model={edition.capability_profile.model}.",),
                ))
            if render.is_stale_for(page):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="draw",
                        code="stale_page_render",
                        message="Active page render is stale for the canonical ComicPage.",
                        artifact_ids=(f"render_{render.revision:03d}",),
                        evidence=(
                            f"Render cites ComicPage revision "
                            f"{render.comic_page_revision} and hash "
                            f"{render.comic_page_sha256}.",
                        ),
                    )
                )
            try:
                analysis = artifacts.read_analysis(
                    selected.page_number,
                    render.revision,
                )
            except ArtifactMissing:
                analysis = None
            dismissed_failure_ids = frozenset(
                issue.id.removeprefix("page-issue-")
                for issue in issues
                if (
                    issue.status == "dismissed"
                    and issue.classification == "invariant_failure"
                    and issue.render_revision == render.revision
                )
            )
            if analysis is None or not _ocr_is_exact(
                page,
                render,
                analysis,
                dismissed_failure_ids=dismissed_failure_ids,
            ):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="draw",
                        code="exact_ocr_status",
                        message="Active page render lacks exact canonical OCR status.",
                        artifact_ids=(f"render_{render.revision:03d}",),
                        evidence=("Every canonical lettering item must match in order.",),
                    )
                )

        width = height = None
        if image is not None and render is not None:
            try:
                with Image.open(io.BytesIO(image)) as opened:
                    opened.load()
                    width, height = opened.size
            except (OSError, ValueError):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="draw",
                        code="corrupt_page_render",
                        message="Active page render is not a readable image.",
                        artifact_ids=(f"render_{render.revision:03d}",),
                        evidence=("Pillow could not decode the complete-page image.",),
                    )
                )
            if (
                width != production.canvas_width
                or height != production.canvas_height
                or render.width != width
                or render.height != height
                or edition.capability_profile.output_width != width
                or edition.capability_profile.output_height != height
            ):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="draw",
                        code="page_render_dimensions",
                        message="Page dimensions do not satisfy render and production lineage.",
                        artifact_ids=(f"render_{render.revision:03d}",),
                        evidence=(
                            f"Image={width}x{height}; render={render.width}x"
                            f"{render.height}; profile="
                            f"{edition.capability_profile.output_width}x"
                            f"{edition.capability_profile.output_height}; production="
                            f"{production.canvas_width}x{production.canvas_height}.",
                        ),
                    )
                )

        known_render_revisions = set(
            artifacts.provenance_revisions(selected.page_number)
        )
        active_lineage: set[int] = set()
        current_revision = render.revision if render is not None else None
        while (
            current_revision is not None
            and current_revision in known_render_revisions
            and current_revision not in active_lineage
        ):
            active_lineage.add(current_revision)
            current_revision = artifacts.read_provenance(
                selected.page_number,
                current_revision,
            ).render.parent_revision
        for issue in issues:
            if issue.page_number != selected.page_number:
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="finish",
                        code="page_issue_lineage",
                        message="Page issue is stored under the wrong page.",
                        artifact_ids=(issue.id,),
                        evidence=(
                            f"Issue identifies page {issue.page_number}; expected "
                            f"{selected.page_number}.",
                        ),
                    )
                )
            if issue.render_revision not in known_render_revisions or (
                issue.resolution_revision is not None
                and issue.resolution_revision not in known_render_revisions
            ):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="finish",
                        code="page_issue_lineage",
                        message="Page issue cites an unknown render revision.",
                        artifact_ids=(issue.id,),
                        evidence=(
                            f"Affected revision {issue.render_revision}; resolution "
                            f"revision {issue.resolution_revision}.",
                        ),
                    )
                )
            elif (
                issue.resolution_revision is not None
                and issue.resolution_revision not in active_lineage
            ):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="finish",
                        code="page_issue_lineage",
                        message=(
                            "Resolved issue revision is not an ancestor of the "
                            "active page render."
                        ),
                        artifact_ids=(
                            issue.id,
                            f"render_{issue.resolution_revision:03d}",
                        ),
                        evidence=(
                            f"Active render lineage is "
                            f"{sorted(active_lineage)!r}.",
                        ),
                    )
                )
        unresolved = tuple(
            issue.id
            for issue in issues
            if issue.status in {"open", "revised"}
            and issue.classification == "editorial_issue"
        )
        accepted = tuple(
            issue.id
            for issue in issues
            if issue.status == "accepted"
            and issue.classification == "editorial_issue"
        )
        open_invariants = [
            issue
            for issue in issues
            if issue.status in {"open", "revised"}
            and issue.classification == "invariant_failure"
        ]
        open_draw = [
            issue for issue in open_invariants if issue.correction_owner == "draw"
        ]
        if open_draw:
            failures.append(
                _failure(
                    page_number=selected.page_number,
                    owner_stage="draw",
                    code="open_draw_invariant",
                    message="Active page has unresolved Draw invariant issues.",
                    artifact_ids=tuple(issue.id for issue in open_draw),
                    evidence=tuple(
                        issue.requested_correction for issue in open_draw
                    ),
                )
            )
        open_upstream = [
            issue for issue in open_invariants if issue.correction_owner != "draw"
        ]
        if open_upstream:
            failures.append(
                _failure(
                    page_number=selected.page_number,
                    owner_stage="adapt",
                    code="open_upstream_invariant",
                    message="Active page has unresolved upstream invariant issues.",
                    artifact_ids=tuple(issue.id for issue in open_upstream),
                    evidence=tuple(
                        issue.requested_correction for issue in open_upstream
                    ),
                )
            )

        creative_codes = tuple(
            dict.fromkeys(
                failure.code
                for failure in failures
                if failure.code in _CREATIVE_FAILURES
            )
        )
        if creative_codes and render is not None:
            correction_requests.append(
                DrawCorrectionRequest(
                    id=f"finish-draw-correction-page-{selected.page_number:03d}",
                    page_number=selected.page_number,
                    render_revision=render.revision,
                    failure_codes=creative_codes,
                    issue_ids=tuple(issue.id for issue in open_draw),
                    requested_correction=(
                        "Generate one corrected complete page revision from the current "
                        "canonical ComicPage; preserve exact lettering and artwork "
                        "outside the cited failures."
                    ),
                )
            )

        normalized_sha256 = None
        if not failures and not unresolved and image is not None:
            normalized_path = artifacts.normalized_page_path(selected.page_number)
            try:
                normalized_sha256 = _normalize_page(
                    image,
                    normalized_path,
                    production,
                )
                normalized_paths.append(normalized_path)
            except (OSError, ValueError, ImageCms.PyCMSError) as exc:
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="finish",
                        code="production_normalization",
                        message="Page cannot be normalized without creative repair.",
                        artifact_ids=(f"render_{render.revision:03d}",),
                        evidence=(str(exc),),
                    )
                )

        preflight_pages.append(
            PreflightPage(
                page_number=selected.page_number,
                comic_page_revision=page.revision,
                comic_page_sha256=page.content_sha256,
                render_revision=render.revision if render is not None else 1,
                render_image_sha256=(
                    render.image_sha256 if render is not None else "0" * 64
                ),
                analysis_render_revision=(
                    analysis.render_revision if analysis is not None else None
                ),
                width=width,
                height=height,
                trim_width=production.trim_width,
                trim_height=production.trim_height,
                bleed_px=production.bleed_px,
                color_profile=(
                    production.color_profile if normalized_sha256 is not None else None
                ),
                normalized_image_sha256=normalized_sha256,
                invariant_failures=tuple(failures),
                diagnostics=tuple(diagnostics),
                unresolved_editorial_issue_ids=unresolved,
                accepted_editorial_issue_ids=accepted,
            )
        )

    preflight = FinishPreflight(
        edition_revision=edition.revision,
        edition_sha256=edition.content_sha256,
        validator_version=FINISH_PREFLIGHT_VALIDATOR_VERSION,
        production=production,
        pages=tuple(preflight_pages),
        correction_requests=tuple(correction_requests),
    )
    if not preflight.ready_to_export:
        if previous_preflight is not None:
            _remove_packages(artifacts, previous_preflight.packages)
        artifacts.write_preflight(preflight)
        return FinishResult(preflight=preflight)

    if not formats:
        packages = _reusable_packages(artifacts, previous_preflight, preflight)
        preflight = FinishPreflight.model_validate(
            preflight.model_copy(update={"packages": packages}).model_dump()
        )
        artifacts.write_preflight(preflight)
        return FinishResult(preflight=preflight, packages=packages)

    try:
        packages = _package_exports(
            artifacts,
            tuple(normalized_paths),
            formats,
            production,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        _clear_derived_outputs(artifacts)
        packaging_failure = InvariantFailure(
            id="finish-export-packaging-integrity",
            owner_stage="finish",
            code="packaging_integrity",
            message="Finish could not produce a verified export package.",
            artifact_ids=tuple(f"page_{number:03d}" for number in range(1, len(pages) + 1)),
            evidence=(str(exc),),
        )
        preflight = FinishPreflight.model_validate(
            preflight.model_copy(
                update={"packaging_failures": (packaging_failure,)}
            ).model_dump()
        )
        artifacts.write_preflight(preflight)
        return FinishResult(preflight=preflight)
    preflight = FinishPreflight.model_validate(
        preflight.model_copy(update={"packages": packages}).model_dump()
    )
    artifacts.write_preflight(preflight)
    return FinishResult(preflight=preflight, packages=packages)
