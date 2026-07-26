"""Draw-owned OCR validation, page issues, and correction routing."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from typing import Protocol

from novel_to_comic.models.draw import (
    AdaptCopyCorrectionRequest,
    LetteringMatch,
    OCRExtraction,
    PageCapabilityProfile,
    PageCorrectionIntent,
    PageIssue,
    PageIssueSummary,
    PageRenderCorrection,
    PageRenderRevision,
    RenderAnalysis,
)
from novel_to_comic.models.page import ComicPage
from novel_to_comic.models.validation import InvariantFailure
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts


PUNCTUATION_POLICY = "unicode_typographic_punctuation_v1"
"""NFC plus typographic quote/apostrophe and ellipsis equivalence.

The policy maps U+2018/U+2019 to ASCII apostrophe, U+201C/U+201D to ASCII
double quote, and U+2026 to three ASCII periods. It does not normalize case,
letters, whitespace, dashes, or any other punctuation.
"""

_PUNCTUATION_EQUIVALENTS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
    }
)


class OCRAdapter(Protocol):
    """Deterministic seam for OCR and observed render geometry."""

    def extract(self, image: bytes) -> OCRExtraction: ...


def normalize_ocr_punctuation(text: str) -> str:
    """Apply the sole canonical OCR punctuation policy."""

    return unicodedata.normalize("NFC", text).translate(_PUNCTUATION_EQUIVALENTS)


def _canonical_lettering(page: ComicPage):
    by_id = {
        lettering.id: lettering
        for content in page.content
        for lettering in content.lettering
    }
    return tuple(by_id[item_id] for item_id in page.reading_order if item_id in by_id)


def _failure(
    *,
    page: ComicPage,
    render: PageRenderRevision,
    code: str,
    message: str,
    artifact_ids: tuple[str, ...],
    evidence: tuple[str, ...],
) -> InvariantFailure:
    return InvariantFailure(
        id=f"draw-page-{page.page_number:03d}-render-{render.revision:03d}-{code}",
        owner_stage="draw",
        code=code,
        message=message,
        artifact_ids=artifact_ids,
        evidence=evidence,
    )


def _compare_lettering(
    page: ComicPage,
    render: PageRenderRevision,
    extraction: OCRExtraction,
) -> tuple[tuple[LetteringMatch, ...], tuple[InvariantFailure, ...]]:
    canonical = _canonical_lettering(page)
    canonical_normalized = [normalize_ocr_punctuation(item.text) for item in canonical]
    observed_normalized = [
        normalize_ocr_punctuation(item.text) for item in extraction.lettering
    ]
    if canonical_normalized == observed_normalized:
        return (
            tuple(
                LetteringMatch(
                    lettering_item_id=item.id,
                    observation_id=observation.id,
                    canonical_text=item.text,
                    observed_text=observation.text,
                )
                for item, observation in zip(
                    canonical,
                    extraction.lettering,
                    strict=True,
                )
            ),
            (),
        )

    canonical_counts = Counter(canonical_normalized)
    observed_counts = Counter(observed_normalized)
    canonical_ids = tuple(item.id for item in canonical)
    evidence = (
        f"canonical={canonical_normalized!r}",
        f"observed={observed_normalized!r}",
        f"punctuation_policy={PUNCTUATION_POLICY}",
    )
    failures: list[InvariantFailure] = []

    if len(canonical_normalized) == len(observed_normalized):
        if canonical_counts == observed_counts:
            failures.append(
                _failure(
                    page=page,
                    render=render,
                    code="reordered_lettering",
                    message="OCR lettering order differs from canonical page order.",
                    artifact_ids=canonical_ids,
                    evidence=evidence,
                )
            )
        elif any(
            observed_count > canonical_counts[text] and text in canonical_counts
            for text, observed_count in observed_counts.items()
        ):
            failures.append(
                _failure(
                    page=page,
                    render=render,
                    code="duplicated_lettering",
                    message="OCR found a duplicated canonical lettering item.",
                    artifact_ids=canonical_ids,
                    evidence=evidence,
                )
            )
        else:
            failures.append(
                _failure(
                    page=page,
                    render=render,
                    code="misspelled_lettering",
                    message="OCR lettering does not exactly match canonical wording.",
                    artifact_ids=canonical_ids,
                    evidence=evidence,
                )
            )
        return (), tuple(failures)

    if len(observed_normalized) < len(canonical_normalized):
        failures.append(
            _failure(
                page=page,
                render=render,
                code="missing_lettering",
                message="OCR did not find every canonical lettering item.",
                artifact_ids=canonical_ids,
                evidence=evidence,
            )
        )
    else:
        duplicated = any(
            observed_count > canonical_counts[text] and text in canonical_counts
            for text, observed_count in observed_counts.items()
        )
        failures.append(
            _failure(
                page=page,
                render=render,
                code="duplicated_lettering" if duplicated else "invented_lettering",
                message=(
                    "OCR found duplicated canonical lettering."
                    if duplicated
                    else "OCR found lettering absent from the canonical page."
                ),
                artifact_ids=canonical_ids,
                evidence=evidence,
            )
        )
    return (), tuple(failures)


def analyze_page_render(
    *,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    ocr: OCRAdapter,
    artifacts: TargetArtifacts,
) -> RenderAnalysis:
    """Extract and persist immutable derived evidence for one page render."""

    if render.is_stale_for(page):
        raise ValueError("page render is stale for the canonical ComicPage")
    image_sha256 = hashlib.sha256(image).hexdigest()
    if image_sha256 != render.image_sha256:
        raise ValueError("page render bytes do not match render lineage")
    extraction = ocr.extract(image)
    matches, failures = _compare_lettering(page, render, extraction)
    analysis = RenderAnalysis(
        page_number=page.page_number,
        render_revision=render.revision,
        render_image_sha256=render.image_sha256,
        punctuation_policy=PUNCTUATION_POLICY,
        recognized_lettering={
            match.lettering_item_id: match.observed_text for match in matches
        },
        ocr_observations=extraction.lettering,
        lettering_matches=matches,
        observed_regions=extraction.observed_regions,
        observed_reading_order=extraction.observed_reading_order,
        invariant_failures=failures,
        evidence=tuple(
            evidence
            for failure in failures
            for evidence in failure.evidence
        ),
    )
    artifacts.write_analysis(analysis)
    return analysis


def record_page_issue(artifacts: TargetArtifacts, issue: PageIssue) -> PageIssue:
    """Append a stable page issue without creating acceptance state."""

    try:
        issues = artifacts.read_issues(issue.page_number)
    except ArtifactMissing:
        issues = ()
    if any(existing.id == issue.id for existing in issues):
        raise ValueError(f"page issue {issue.id!r} already exists")
    artifacts.write_issues(issue.page_number, (*issues, issue))
    return issue


def summarize_page_issues(
    artifacts: TargetArtifacts,
    *,
    page_number: int | None = None,
) -> PageIssueSummary:
    """Summarize exceptions before Continue to Book."""

    if page_number is not None:
        paths = (artifacts.issues_path(page_number),)
    else:
        paths = tuple(
            sorted((artifacts.project_dir / "draw" / "pages").glob("page_*/issues.json"))
        )
    issues: list[PageIssue] = []
    for path in paths:
        if path.exists():
            number = int(path.parent.name.removeprefix("page_"))
            issues.extend(artifacts.read_issues(number))
    return PageIssueSummary(
        unresolved_issue_ids=tuple(
            issue.id for issue in issues if issue.status == "open"
        ),
        blocking_issue_ids=tuple(
            issue.id
            for issue in issues
            if issue.status == "open"
            and issue.classification == "invariant_failure"
        ),
        accepted_editorial_issue_ids=tuple(
            issue.id for issue in issues if issue.status == "accepted"
        ),
    )


def request_issue_correction(
    issue: PageIssue,
    *,
    profile: PageCapabilityProfile,
) -> AdaptCopyCorrectionRequest | PageCorrectionIntent:
    """Route copy upstream or select a supported complete-page edit mode."""

    if issue.status != "open":
        raise ValueError("only an open page issue can request correction")
    if issue.correction_owner == "adapt":
        return AdaptCopyCorrectionRequest(
            issue_id=issue.id,
            page_number=issue.page_number,
            requested_change=issue.requested_correction,
            source_unit_ids=issue.source_unit_ids,
            adapted_beat_ids=issue.adapted_beat_ids,
            lettering_item_ids=issue.lettering_item_ids,
        )
    mode = "region_targeted" if issue.detected_region_ids else "instructed"
    if mode not in profile.editing_modes:
        label = "region-targeted" if mode == "region_targeted" else "instructed"
        raise ValueError(f"selected profile does not support {label} correction")
    return PageCorrectionIntent(
        issue_id=issue.id,
        page_number=issue.page_number,
        parent_render_revision=issue.render_revision,
        mode=mode,
        instruction=issue.requested_correction,
        detected_region_ids=issue.detected_region_ids,
    )


def build_correction_request(
    *,
    issue: PageIssue,
    page: ComicPage,
    parent: PageRenderRevision,
    profile: PageCapabilityProfile,
    artifacts: TargetArtifacts,
) -> PageRenderCorrection:
    """Attach canonical and render lineage to a supported Draw correction."""

    intent = request_issue_correction(issue, profile=profile)
    if isinstance(intent, AdaptCopyCorrectionRequest):
        raise ValueError("copy changes must return to Adapt and Plan")
    if parent.page_number != page.page_number or parent.revision != issue.render_revision:
        raise ValueError("correction parent does not match the affected render")
    if parent.is_stale_for(page):
        raise ValueError("correction parent is stale for the canonical ComicPage")
    parent_bytes = artifacts.read_render(parent.page_number, parent.revision)
    if hashlib.sha256(parent_bytes).hexdigest() != parent.image_sha256:
        raise ValueError("correction parent bytes do not match render lineage")
    if intent.detected_region_ids:
        analysis = artifacts.read_analysis(parent.page_number, parent.revision)
        known_regions = {region.id for region in analysis.observed_regions}
        if any(region_id not in known_regions for region_id in intent.detected_region_ids):
            raise ValueError("page issue cites an unknown detected region")
    return PageRenderCorrection(
        issue_id=issue.id,
        page_number=page.page_number,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        parent_render_revision=parent.revision,
        parent_render_image_sha256=parent.image_sha256,
        mode=intent.mode,
        instruction=intent.instruction,
        detected_region_ids=intent.detected_region_ids,
    )


def resolve_page_issue(
    artifacts: TargetArtifacts,
    *,
    issue_id: str,
    page_number: int,
    resolution_revision: int,
) -> PageIssue:
    """Link an issue to the complete page revision produced for it."""

    issues = artifacts.read_issues(page_number)
    resolved: PageIssue | None = None
    updated: list[PageIssue] = []
    for issue in issues:
        if issue.id == issue_id:
            if issue.status != "open":
                raise ValueError("only an open page issue can be resolved")
            resolved = issue.model_copy(
                update={
                    "status": "resolved",
                    "resolution_revision": resolution_revision,
                }
            )
            resolved = PageIssue.model_validate(resolved.model_dump())
            updated.append(resolved)
        else:
            updated.append(issue)
    if resolved is None:
        raise ValueError(f"page issue {issue_id!r} was not found")
    artifacts.write_issues(page_number, tuple(updated))
    return resolved


def accept_editorial_page_issue(
    artifacts: TargetArtifacts,
    *,
    issue_id: str,
    page_number: int,
) -> PageIssue:
    """Deliberately accept one editorial exception; invariants remain blocking."""

    issues = artifacts.read_issues(page_number)
    accepted: PageIssue | None = None
    updated: list[PageIssue] = []
    for issue in issues:
        if issue.id == issue_id:
            if issue.status != "open":
                raise ValueError("only an open page issue can be accepted")
            if issue.classification == "invariant_failure":
                raise ValueError("an invariant failure cannot be deliberately accepted")
            accepted = PageIssue.model_validate(
                issue.model_copy(update={"status": "accepted"}).model_dump()
            )
            updated.append(accepted)
        else:
            updated.append(issue)
    if accepted is None:
        raise ValueError(f"page issue {issue_id!r} was not found")
    artifacts.write_issues(page_number, tuple(updated))
    return accepted
