"""Draw-owned OCR validation, page issues, and correction routing."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict

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
from novel_to_comic.models.validation import EditorialIssue, InvariantFailure
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.text_utils import normalize_display_text
from novel_to_comic.usage import ApiResult, UsageRecord


PUNCTUATION_POLICY = "typographic_lettering_v2"
"""NFC, typographic quote/dash/ellipsis equivalence, and whitespace collapse.

Comparing canonical lettering to OCR output is comparing two producers that do
not agree on formatting. A letterer wraps a balloon across lines, an OCR engine
reads an em dash as a hyphen and a curly apostrophe as a straight one. None of
that changes the words, so the policy folds all of it.

It deliberately does NOT normalize case or letters: "It Wasn't" is a real
lettering defect, not a formatting variant.
"""


class OCRAdapter(Protocol):
    """Deterministic seam for OCR and observed render geometry."""

    async def extract(self, image: bytes) -> "ApiResult[OCRExtraction]": ...


class PageAnalysisResult(BaseModel):
    """Persisted render evidence plus the billable usage that produced it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis: RenderAnalysis
    usage: UsageRecord | None = None


def normalize_ocr_punctuation(text: str) -> str:
    """Apply the sole canonical lettering comparison policy."""

    return normalize_display_text(text)


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


def _region_order_contradicts(
    matches: tuple[LetteringMatch, ...],
    extraction: OCRExtraction,
) -> bool:
    """True only when detected geometry proves the rendered order is wrong.

    An OCR engine's own observation order is a heuristic sweep of the image, so
    a differing flat order is not evidence of a defect. Distinct detected
    regions placed in a contradicting reading order are.
    """

    if not extraction.observed_reading_order:
        return False
    region_by_observation = {
        observation.id: observation.detected_region_id
        for observation in extraction.lettering
    }
    canonical_regions: list[str] = []
    for match in matches:
        region_id = region_by_observation.get(match.observation_id)
        if region_id is None:
            return False
        if not canonical_regions or canonical_regions[-1] != region_id:
            canonical_regions.append(region_id)
    if len(set(canonical_regions)) < 2:
        return False
    remaining = list(extraction.observed_reading_order)
    for region_id in canonical_regions:
        if region_id not in remaining:
            return True
        remaining = remaining[remaining.index(region_id) + 1 :]
    return False


def _compare_lettering(
    page: ComicPage,
    render: PageRenderRevision,
    extraction: OCRExtraction,
) -> tuple[
    tuple[LetteringMatch, ...],
    tuple[InvariantFailure, ...],
    tuple[EditorialIssue, ...],
]:
    canonical = _canonical_lettering(page)
    canonical_normalized = [normalize_ocr_punctuation(item.text) for item in canonical]
    observed_normalized = [
        normalize_ocr_punctuation(item.text) for item in extraction.lettering
    ]
    canonical_counts = Counter(canonical_normalized)
    observed_counts = Counter(observed_normalized)
    canonical_ids = tuple(item.id for item in canonical)
    evidence = (
        f"canonical={canonical_normalized!r}",
        f"observed={observed_normalized!r}",
        f"punctuation_policy={PUNCTUATION_POLICY}",
    )
    failures: list[InvariantFailure] = []
    issues: list[EditorialIssue] = []

    missing = sorted((canonical_counts - observed_counts).elements())
    surplus = sorted((observed_counts - canonical_counts).elements())
    duplicated = sorted(
        text
        for text, count in observed_counts.items()
        if text in canonical_counts and count > canonical_counts[text]
    )
    if missing and surplus:
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
    elif missing:
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
    elif duplicated:
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
    elif surplus:
        failures.append(
            _failure(
                page=page,
                render=render,
                code="invented_lettering",
                message="OCR found lettering absent from the canonical page.",
                artifact_ids=canonical_ids,
                evidence=evidence,
            )
        )
    if failures:
        return (), tuple(failures), ()

    # Every canonical string is present exactly once. Pair each canonical item
    # with the observation carrying its wording rather than with the observation
    # at the same index, so a geometric sweep order cannot break the match.
    available: dict[str, list[int]] = {}
    for index, text in enumerate(observed_normalized):
        available.setdefault(text, []).append(index)
    matches: list[LetteringMatch] = []
    for item, text in zip(canonical, canonical_normalized, strict=True):
        observation = extraction.lettering[available[text].pop(0)]
        matches.append(
            LetteringMatch(
                lettering_item_id=item.id,
                observation_id=observation.id,
                canonical_text=item.text,
                observed_text=observation.text,
            )
        )
    ordered = tuple(matches)

    observation_order = [
        observation.id for observation in extraction.lettering
    ]
    matched_order = [match.observation_id for match in ordered]
    if matched_order != [
        observation_id
        for observation_id in observation_order
        if observation_id in set(matched_order)
    ]:
        if _region_order_contradicts(ordered, extraction):
            failures.append(
                _failure(
                    page=page,
                    render=render,
                    code="reordered_lettering",
                    message="Detected page regions contradict canonical reading order.",
                    artifact_ids=canonical_ids,
                    evidence=(
                        *evidence,
                        f"observed_reading_order={extraction.observed_reading_order!r}",
                    ),
                )
            )
            return ordered, tuple(failures), ()
        issues.append(
            EditorialIssue(
                id=(
                    f"draw-page-{page.page_number:03d}-render-{render.revision:03d}"
                    "-unverified_lettering_order"
                ),
                owner_stage="draw",
                code="unverified_lettering_order",
                message="OCR read the canonical lettering in a different order.",
                artifact_ids=list(canonical_ids),
                evidence=[
                    *evidence,
                    "Detected regions do not prove a reading-order defect; "
                    "review the page order visually.",
                ],
            )
        )
    return ordered, (), tuple(issues)


async def analyze_page_render(
    *,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    ocr: OCRAdapter,
    artifacts: TargetArtifacts,
) -> PageAnalysisResult:
    """Extract and persist immutable derived evidence for one page render."""

    if render.is_stale_for(page):
        raise ValueError("page render is stale for the canonical ComicPage")
    image_sha256 = hashlib.sha256(image).hexdigest()
    if image_sha256 != render.image_sha256:
        raise ValueError("page render bytes do not match render lineage")
    read = await ocr.extract(image)
    extraction = read.value
    matches, failures, issues = _compare_lettering(page, render, extraction)
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
        editorial_issues=issues,
        evidence=tuple(
            evidence
            for result in (*failures, *issues)
            for evidence in result.evidence
        ),
        analysis_usage=read.usage,
    )
    artifacts.write_analysis(analysis)
    return PageAnalysisResult(analysis=analysis, usage=read.usage)


def record_analysis_issues(
    artifacts: TargetArtifacts,
    analysis: RenderAnalysis,
    *,
    lettering_item_ids: tuple[str, ...] = (),
) -> tuple[PageIssue, ...]:
    """Turn render-analysis evidence into the page issues that gate Book.

    Without this, an OCR invariant failure lives only inside the derived
    analysis: ``PageIssueSummary`` sees nothing open and Continue to Book stays
    enabled on a page whose lettering is provably wrong.
    """

    recorded: list[PageIssue] = []
    for result in (*analysis.invariant_failures, *analysis.editorial_issues):
        invariant = result.kind == "invariant_failure"
        issue = PageIssue(
            id=f"page-issue-{result.id}",
            issue_type=result.code,
            classification="invariant_failure" if invariant else "editorial_issue",
            correction_kind="render_fidelity",
            correction_owner="draw",
            page_number=analysis.page_number,
            render_revision=analysis.render_revision,
            evidence=result.evidence,
            requested_correction=(
                f"{result.message} Render one corrected complete page whose visible "
                "lettering matches the canonical ComicPage exactly."
            ),
            lettering_item_ids=lettering_item_ids or result.artifact_ids,
            detected_region_ids=(),
            status="open",
        )
        try:
            recorded.append(record_page_issue(artifacts, issue))
        except ValueError:
            # Re-analysing the same immutable render is idempotent by design.
            continue
    return tuple(recorded)


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
