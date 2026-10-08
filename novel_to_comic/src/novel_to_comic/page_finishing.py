"""Provider-free final-book validation, normalization, and packaging."""

from __future__ import annotations

from novel_to_comic.artifact_lock import locked_mutation

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import img2pdf
from PIL import Image, ImageCms, ImageDraw, ImageFont
from pypdf import PdfReader

from novel_to_comic.appearance_chronology import CODE as CHRONOLOGY_CODE, appearance_chronology
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
from novel_to_comic.page_drawing import page_profile_uses_native_dimensions
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import series_root
from novel_to_comic.verified_files import verified_file, verified_stream


_CREATIVE_FAILURES = {
    "corrupt_page_render",
    "page_render_dimensions",
    "render_lineage",
    "stale_page_render",
    "lettering_mismatch",
    "open_draw_invariant",
}


def _native_dimension_render(render: PageRenderRevision) -> bool:
    """Renders from the Codex route keep the provider's native page size."""
    return render.provider == "codex-dev" and render.model == "gpt-image-2"


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


def _appearance_diagnostics(
    adaptation: BookAdaptation,
    pages: tuple[ComicPage, ...],
) -> dict[int, list[PreflightDiagnostic]]:
    """Check explicit state chronology before exporting the edition."""

    return {
        page_number: [
            _diagnostic(
                page_number=page_number,
                owner_stage=finding.owner_stage,
                code=CHRONOLOGY_CODE,
                message=finding.message,
                artifact_ids=finding.artifact_ids,
                evidence=finding.evidence,
            )
            for finding in findings
        ]
        for page_number, findings in appearance_chronology(adaptation, pages).items()
    }


def _load_active_render(
    artifacts: TargetArtifacts,
    page_number: int,
    *,
    load_image: bool = True,
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
    provenance = provenance_by_revision[artifacts.active_render_revision(page_number)]
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
    image = None
    if load_image:
        try:
            image = artifacts.read_render(page_number, render.revision)
        except ArtifactMissing:
            pass
        matches = image is not None and hashlib.sha256(image).hexdigest() == render.image_sha256
    else:
        matches = verified_file(artifacts.render_path(page_number, render.revision), render.image_sha256)
    if not matches:
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
                page.lettering_sha256,
                page.composite_identity,
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


def package_is_current(artifacts: TargetArtifacts, package: ExportPackage) -> bool:
    """Validate a saved package without changing any files or loading it in memory."""
    path = _safe_package_path(artifacts, package.relative_path)
    if path is None:
        return False
    return verified_file(path, package.content_sha256, byte_size=package.byte_size)


@locked_mutation
def current_preflight(artifacts: TargetArtifacts, *, require_ready: bool = False) -> FinishPreflight:
    """The shared validity gate for derived Finish reads."""
    preflight = artifacts.read_preflight()
    if preflight.validator_version != FINISH_PREFLIGHT_VALIDATOR_VERSION:
        raise ValueError("Finish preflight must be refreshed")
    if require_ready and not preflight.ready_to_export:
        raise ValueError("Resolve the current Finish checks before exporting")
    if require_ready:
        edition, plan = artifacts.read_book_edition(), artifacts.read_plan()
        if (edition.revision, edition.content_sha256) != (preflight.edition_revision, preflight.edition_sha256):
            raise ValueError("The edition changed; refresh Finish")
        if len(plan.pages) != len(preflight.pages):
            raise ValueError("The plan changed; refresh Finish")
        for selected, checked in zip(plan.pages, preflight.pages):
            page = artifacts.read_page(selected.page_number)
            render, _image, failures = _load_active_render(artifacts, selected.page_number, load_image=False)
            if (failures or render is None
                or (selected.page_number, selected.revision, selected.content_sha256)
                   != (checked.page_number, checked.comic_page_revision, checked.comic_page_sha256)
                or (page.revision, page.content_sha256) != (selected.revision, selected.content_sha256)
                or (render.revision, render.image_sha256) != (checked.render_revision, checked.render_image_sha256)):
                raise ValueError("Page inputs changed; refresh Finish")
            if checked.lettering_sha256 is not None:
                from novel_to_comic.lettering.service import composite_identity
                lettering = artifacts.read_lettering(checked.page_number)
                style = artifacts.read_lettering_style()
                if (lettering.revision, lettering.content_sha256) != (checked.lettering_revision, checked.lettering_sha256) or composite_identity(render, lettering, style) != checked.composite_identity:
                    raise ValueError("Lettering changed; refresh Finish")
            normalized = artifacts.normalized_page_path(checked.page_number)
            if not verified_file(normalized, checked.normalized_image_sha256):
                raise ValueError(f"Normalized page {checked.page_number} changed; refresh Finish")
    if any(not package_is_current(artifacts, package) for package in preflight.packages):
        raise ValueError("An export package is unavailable; refresh Finish preflight")
    return preflight


@locked_mutation
def open_verified_package(artifacts: TargetArtifacts, fmt: str):
    """Open verified bytes while locked; the descriptor survives invalidation.

    The caller owns closing the descriptor. Streaming it does not retain a
    whole book in memory or reopen an invalidated path after verification.
    """
    preflight = current_preflight(artifacts, require_ready=True)
    package = next((item for item in preflight.packages if item.format == fmt), None)
    if package is None:
        raise ValueError(f"No current {fmt} package is available. Run Finish first.")
    path = _safe_package_path(artifacts, package.relative_path)
    if path != artifacts.export_path(fmt).resolve():
        raise ValueError("Export package path does not match its format. Refresh Finish.")
    stream = path.open("rb")
    try:
        if not verified_stream(stream, package.content_sha256, byte_size=package.byte_size):
            raise ValueError("Export bytes changed. Refresh Finish.")
        stream.seek(0)
        return stream, package, preflight
    except BaseException:
        stream.close()
        raise


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
        if package_is_current(artifacts, package):
            reusable.append(package)
    stale = tuple(package for package in previous.packages if package not in reusable)
    _remove_packages(artifacts, stale)
    return tuple(reusable)


def source_credit_info(project_dir: Path) -> dict | None:
    """Return the mandatory attribution for a share-alike sample, if present.

    The attribution describes the uploaded source, so it lives at the series
    root and applies to every part's book.
    """
    source_path = series_root(project_dir) / "sample_source.json"
    if not source_path.exists():
        return None
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ValueError("Sample source attribution is invalid")
    if source.get("license") != "CC BY-SA 3.0":
        return None
    title, author, source_url, license_url = (
        source.get(key) for key in ("title", "author", "source_url", "license_url")
    )
    if not all(isinstance(value, str) and value.strip() for value in (title, author, source_url, license_url)):
        raise ValueError("Share-alike sample is missing export attribution")
    if not source_url.startswith("https://scp-wiki.wikidot.com/"):
        raise ValueError("Share-alike source needs a specific export credit format")
    return {"title": title, "author": author, "source_url": source_url, "license": source["license"], "license_url": license_url}


def source_credit_page(project_dir: Path, production: FinishProductionSpec) -> bytes | None:
    """Include a readable share-alike notice in every exported adaptation."""
    source = source_credit_info(project_dir)
    if source is None:
        return None
    title, author, source_url, license_url = (
        source[key] for key in ("title", "author", "source_url", "license_url")
    )

    width, height = production.canvas_width, production.canvas_height
    image = Image.new("RGB", (width, height), "#f6f0e4")
    draw = ImageDraw.Draw(image)
    font_path = Path(__file__).with_name("fonts") / "EBGaramond-SemiBold.ttf"
    margin = max(8, width // 12)
    paragraphs = (
        "SOURCE & LICENSE",
        f'Based on "{title}" by {author}, from the SCP Wiki.',
        f"Original story: {source_url}",
        "This comic adaptation is licensed under Creative Commons Attribution-ShareAlike 3.0 Unported.",
        license_url,
    )

    def wrapped_lines(font: ImageFont.FreeTypeFont) -> list[str]:
        lines: list[str] = []
        max_width = width - 2 * margin
        for paragraph in paragraphs:
            if lines:
                lines.append("")
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}" if line else word
                if draw.textlength(candidate, font=font) <= max_width:
                    line = candidate
                    continue
                if line:
                    lines.append(line)
                    line = ""
                for character in word:
                    if line and draw.textlength(line + character, font=font) > max_width:
                        lines.append(line)
                        line = ""
                    line += character
            if line:
                lines.append(line)
        return lines

    for size in range(max(7, min(width // 20, height // 28)), 5, -1):
        font = ImageFont.truetype(font_path, size)
        lines = wrapped_lines(font)
        leading = max(2, size // 3)
        line_height = size + leading
        if len(lines) * line_height <= height - 2 * margin:
            break
    else:
        raise ValueError("Share-alike attribution does not fit the export page")

    y = margin
    for line in lines:
        if line:
            draw.text((margin, y), line, font=font, fill="#191714")
        y += line_height
    output = io.BytesIO()
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    image.save(output, "JPEG", icc_profile=srgb.tobytes(), dpi=(production.dpi, production.dpi), quality=production.jpeg_quality, subsampling=0)
    return output.getvalue()


def _package_exports(
    artifacts: TargetArtifacts,
    page_paths: tuple[Path, ...],
    formats: tuple[str, ...],
    productions: tuple[FinishProductionSpec, ...],
) -> tuple[ExportPackage, ...]:
    packages: list[ExportPackage] = []
    credit_page = source_credit_page(artifacts.project_dir, productions[-1])
    exported_pages: tuple[str | bytes, ...] = tuple(str(path) for path in page_paths) + ((credit_page,) if credit_page else ())
    export_productions = productions + ((productions[-1],) if credit_page else ())
    page_numbers = tuple(range(1, len(exported_pages) + 1))
    for format in formats:
        output = artifacts.export_path(format)
        if format == "pdf":
            _atomic_write(output, img2pdf.convert(list(exported_pages)))
            pdf = PdfReader(output)
            if len(pdf.pages) != len(exported_pages):
                raise ValueError("PDF page count does not match the active book")
            for page, production in zip(pdf.pages, export_productions, strict=True):
                expected_width = production.canvas_width / production.dpi * 72
                expected_height = production.canvas_height / production.dpi * 72
                if (
                    abs(float(page.mediabox.width) - expected_width) > 0.02
                    or abs(float(page.mediabox.height) - expected_height) > 0.02
                ):
                    raise ValueError("PDF page dimensions do not match production")
        elif format == "cbz":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for page_number, page_input in zip(page_numbers, exported_pages, strict=True):
                    archive.writestr(
                        f"page_{page_number:03d}.jpg",
                        Path(page_input).read_bytes() if isinstance(page_input, str) else page_input,
                    )
            _atomic_write(output, buffer.getvalue())
            with zipfile.ZipFile(output) as archive:
                expected = [f"page_{number:03d}.jpg" for number in page_numbers]
                if archive.namelist() != expected or archive.testzip() is not None:
                    raise ValueError("CBZ order or archive integrity is invalid")
                for name, production in zip(expected, export_productions, strict=True):
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


@locked_mutation
def finish_book(
    artifacts: TargetArtifacts,
    *,
    production: FinishProductionSpec | None = None,
    dpi: int = 300,
    formats: tuple[str, ...] = ("pdf", "cbz"),
    clear_derived_outputs: bool = True,
) -> FinishResult:
    """Export verified pages; an explicit production spec is a fixed constraint.

    Native-profile pages default to their full decoded canvas at ``dpi``.
    Their saved book-wide production dimensions remain composition intent;
    PreflightPage records the actual per-page canvas and full-page trim.
    """

    previous_preflight = (
        _read_existing_preflight(artifacts)
        if not clear_derived_outputs and not formats
        else None
    )
    plan = artifacts.read_plan()
    adaptation = artifacts.read_adaptation()
    edition = artifacts.read_book_edition()
    # Missing inputs fail before any current package is removed.
    if clear_derived_outputs:
        _clear_derived_outputs(artifacts)
    edition_native_dimensions = page_profile_uses_native_dimensions(edition.capability_profile)
    production_requested = production is not None
    if production is None:
        production = FinishProductionSpec(
            canvas_width=edition.capability_profile.output_width,
            canvas_height=edition.capability_profile.output_height,
            dpi=dpi,
        )
    pages = tuple(artifacts.read_page(item.page_number) for item in plan.pages)
    # Seed every missing presentation before creating any normalized output.
    # Initial lettering writes invalidate Finish, so lazy seeding inside the
    # loop would delete earlier pages during a book's first multi-page export.
    lettering_setup_errors: dict[int, str] = {}
    if not edition.capability_profile.exact_visible_lettering:
        from novel_to_comic.lettering.service import ensure_lettering
        for page in pages:
            try:
                ensure_lettering(artifacts, page.page_number)
            except (OSError, ValueError, ArtifactMissing, ArtifactInvalid) as exc:
                lettering_setup_errors[page.page_number] = str(exc)
    # Optional OCR evidence is read-only here. Export never runs or repairs a checker.
    analyses: dict[int, RenderAnalysis] = {}
    for page in pages:
        revisions = artifacts.provenance_revisions(page.page_number)
        if not revisions:
            continue
        render = artifacts.read_provenance(page.page_number, artifacts.active_render_revision(page.page_number)).render
        try:
            analysis = artifacts.read_analysis(page.page_number, render.revision)
            if (analysis.render_image_sha256 == render.image_sha256
                    and analysis.comic_page_sha256 == page.content_sha256):
                analyses[page.page_number] = analysis
        except (ArtifactMissing, ArtifactInvalid, ValueError):
            pass
    appearance = _appearance_diagnostics(adaptation, pages)
    preflight_pages: list[PreflightPage] = []
    correction_requests: list[DrawCorrectionRequest] = []
    normalized_paths: list[Path] = []
    page_productions: list[FinishProductionSpec] = []

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
        # A render keeps the geometry of the route that drew it; pages retained
        # across an edition profile advance are checked against their own route.
        native_dimensions = edition_native_dimensions or (
            render is not None and _native_dimension_render(render)
        )
        if render is not None:
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
            analysis = analyses.get(page.page_number)

        width = height = None
        page_production = production
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
            if native_dimensions and not production_requested and width is not None and height is not None:
                page_production = FinishProductionSpec(
                    canvas_width=width, canvas_height=height, dpi=dpi,
                )
            if (
                render.width != width
                or render.height != height
                or (
                    not native_dimensions
                    and (
                        production.canvas_width != width
                        or production.canvas_height != height
                    )
                )
                or (
                    not native_dimensions
                    and (
                        edition.capability_profile.output_width != width
                        or edition.capability_profile.output_height != height
                    )
                )
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
                            f"{edition.capability_profile.output_height}.",
                        ),
                    )
                )
            if native_dimensions and page_production is not None and (
                width != page_production.canvas_width
                or height != page_production.canvas_height
                or page_production.bleed_px != 0
            ):
                failures.append(
                    _failure(
                        page_number=selected.page_number,
                        owner_stage="finish",
                        code="production_geometry",
                        message="Requested production geometry cannot preserve the full page.",
                        artifact_ids=(f"render_{render.revision:03d}",),
                        evidence=(
                            f"Image={width}x{height}; requested canvas="
                            f"{page_production.canvas_width}x{page_production.canvas_height}; "
                            f"bleed={page_production.bleed_px}. Finish does not crop or resize.",
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
            if not issue.requires_resolution:
                continue
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
            and issue.requires_resolution
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
            and issue.requires_resolution
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

        lettering_placement_review_needed = False
        lettering_revision = None
        lettering_sha256 = None
        composite_key = None
        if (not failures and not unresolved and image is not None and render is not None
                and not edition.capability_profile.exact_visible_lettering):
            from novel_to_comic.lettering.service import composite_page, placement_review_needed
            try:
                if selected.page_number in lettering_setup_errors:
                    raise ValueError(lettering_setup_errors[selected.page_number])
                composite_path, composite_key = composite_page(artifacts, selected.page_number,
                                                              expected_render_revision=render.revision)
                state = artifacts.read_lettering(selected.page_number)
                lettering_revision, lettering_sha256 = state.revision, state.content_sha256
                lettering_placement_review_needed = placement_review_needed(state, render)
                image = composite_path.read_bytes()
            except (OSError, ValueError) as exc:
                failures.append(_failure(
                    page_number=selected.page_number, owner_stage="finish", code="lettering_layout",
                    message="Open Lettering to resolve this page's layout. No artwork redraw is required.",
                    artifact_ids=(f"lettering/page_{selected.page_number:03d}",), evidence=(str(exc),),
                ))
        normalized_sha256 = None
        if not failures and not unresolved and image is not None and page_production is not None:
            normalized_path = artifacts.normalized_page_path(selected.page_number)
            try:
                normalized_sha256 = _normalize_page(
                    image,
                    normalized_path,
                    page_production,
                )
                normalized_paths.append(normalized_path)
                page_productions.append(page_production)
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
                trim_width=page_production.trim_width if page_production is not None else None,
                trim_height=page_production.trim_height if page_production is not None else None,
                bleed_px=page_production.bleed_px if page_production is not None else 0,
                color_profile=(
                    page_production.color_profile if normalized_sha256 is not None else None
                ),
                normalized_image_sha256=normalized_sha256,
                lettering_revision=lettering_revision, lettering_sha256=lettering_sha256,
                composite_identity=composite_key,
                lettering_placement_review_needed=lettering_placement_review_needed,
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
            tuple(page_productions),
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
