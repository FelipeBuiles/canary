"""Draw-owned OCR validation, page issues, and correction routing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import Counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.draw import (
    AdaptCopyCorrectionRequest,
    CorrectionChange,
    LetteringMatch,
    OCRExtraction,
    PageCapabilityProfile,
    PageCorrectionIntent,
    PageIssue,
    PageIssueSummary,
    PageRenderCorrection,
    PageRenderRevision,
    RenderAnalysis,
    RawOCRObservation,
)
from novel_to_comic.models.page import ComicPage
from novel_to_comic.models.validation import EditorialIssue, InvariantFailure
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.text_utils import normalize_display_text
from novel_to_comic.usage import ApiResult, UsageRecord

logger = logging.getLogger(__name__)

MAX_CORRECTION_CHANGES = 24
MAX_CORRECTION_NOTE_CHARACTERS = 1000
MAX_CORRECTION_ANNOTATIONS = 24
MAX_CORRECTION_CONTEXT_SOURCE_CHARACTERS = 6000
MAX_CORRECTION_CONTEXT_SELECTED_UNITS = 32
DRAW_VALIDATOR_VERSION = "panel_order_v3_hybrid_v1"


class StaleCorrectionError(ValueError):
    """The correction cites a superseded page or render revision."""


class InvalidCorrectionError(ValueError):
    """The correction selection, notes, or geometry cannot be executed."""


class PageCorrectionContext(BaseModel):
    """Grounded bookwide context compiled for one correction, with provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    beat_ids: tuple[str, ...] = ()
    beat_summaries: tuple[str, ...] = ()
    treatment_spine: tuple[str, ...] = ()
    appearance_chronology: tuple[str, ...] = ()
    beat_transitions: tuple[str, ...] = ()
    source_unit_ids: tuple[str, ...] = ()
    source_texts: tuple[str, ...] = ()
    selected_source_unit_ids: tuple[str, ...] = ()
    omitted_source_unit_ids: tuple[str, ...] = ()
    adaptation_revision: int = Field(ge=1)
    adaptation_sha256: str = Field(min_length=64, max_length=64)
    digest: str = Field(min_length=1)
    truncated: bool = False

    def prompt_section(self) -> str:
        lines = [
            "Bookwide story context (read-only grounding; canonical lettering above stays exact):",
        ]
        for spine in self.treatment_spine:
            lines.append(f"- Spine: {spine}")
        for beat_id, summary in zip(self.beat_ids, self.beat_summaries, strict=True):
            lines.append(f"- Beat {beat_id}: {summary}")
        for change in self.appearance_chronology:
            lines.append(f"- Appearance: {change}")
        for transition in self.beat_transitions:
            lines.append(f"- Continuity: {transition}")
        for unit_id, text in zip(self.source_unit_ids, self.source_texts, strict=True):
            lines.append(f"- Source {unit_id}: {text}")
        if self.truncated:
            lines.append("- (source passages truncated to the correction context budget)")
        return "\n".join(lines)

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

    if not extraction.reading_order_proven or not extraction.observed_reading_order:
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
    if len(canonical_regions) < 2:
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
        f"expected_text={json.dumps(canonical_normalized, ensure_ascii=False)}",
        f"recognized_text={json.dumps(observed_normalized, ensure_ascii=False)}",
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
    order_is_provable = (
        extraction.reading_order_proven
        and len(set(canonical_normalized)) == len(canonical_normalized)
    )
    matched_order = [match.observation_id for match in ordered]
    if order_is_provable and _region_order_contradicts(ordered, extraction):
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
    if (not order_is_provable and len(matches) > 1) or matched_order != [
        observation_id
        for observation_id in observation_order
        if observation_id in set(matched_order)
    ]:
        issues.append(
            EditorialIssue(
                id=(
                    f"draw-page-{page.page_number:03d}-render-{render.revision:03d}"
                    "-unverified_lettering_order"
                ),
                owner_stage="draw",
                code="unverified_lettering_order",
                message="OCR panel geometry does not establish the complete lettering order.",
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
    try:
        analysis = revalidate_cached_page_render(page=page, render=render, artifacts=artifacts)
        return PageAnalysisResult(analysis=analysis, usage=None)
    except ArtifactMissing as exc:
        if exc.name != "raw_ocr":
            # A missing downstream issue/artifact is not evidence that the paid
            # observations are absent, and must never trigger another OCR call.
            raise
    from novel_to_comic.page_ocr import GatewayPageOCRAdapter
    if isinstance(ocr, GatewayPageOCRAdapter):
        ocr.bind_render(artifacts, render)
    read = await ocr.extract(image)
    raw = RawOCRObservation(
        page_number=page.page_number, render_revision=render.revision,
        render_image_sha256=render.image_sha256, extraction=read.value, usage=read.usage,
        figures_read=True,
    )
    artifacts.write_raw_ocr(raw)
    analysis = _validate_observations(page=page, render=render, raw=raw, artifacts=artifacts)
    await asyncio.to_thread(_reseed_lettering, artifacts, page.page_number)
    return PageAnalysisResult(analysis=analysis, usage=read.usage)


def _reseed_lettering(artifacts: TargetArtifacts, page_number: int) -> None:
    """Let untouched editable lettering use the new read (faces). Never fails the read."""
    from novel_to_comic.lettering.service import reseed_after_read

    try:
        reseed_after_read(artifacts, page_number)
    except Exception:
        logger.warning("Page %s lettering was not re-placed after its read", page_number, exc_info=True)


def revalidate_cached_page_render(
    *, page: ComicPage, render: PageRenderRevision, artifacts: TargetArtifacts,
) -> RenderAnalysis:
    """Provider-free validation used by Draw retries and Finish preflight."""
    if render.is_stale_for(page):
        raise ValueError("page render is stale for the canonical ComicPage")
    saved = None
    if artifacts.analysis_path(page.page_number, render.revision).exists():
        saved = artifacts.read_analysis(page.page_number, render.revision)
        if saved.render_image_sha256 != render.image_sha256:
            raise ValueError("saved OCR analysis belongs to different render bytes")
        if (saved.validator_version == DRAW_VALIDATOR_VERSION
                and saved.comic_page_sha256 == render.comic_page_sha256):
            record_analysis_issues(artifacts, saved)
            return saved
    try:
        raw = artifacts.read_raw_ocr(page.page_number, render.revision)
    except ArtifactMissing:
        if saved is None:
            try:
                response = artifacts.read_ocr_response(page.page_number, render.revision)
            except ArtifactMissing:
                # Retain the raw_ocr absence signal; only this authorizes OCR.
                raise ArtifactMissing("raw_ocr", artifacts.raw_ocr_path(page.page_number, render.revision))
            if (response.page_number != page.page_number
                    or response.render_revision != render.revision
                    or response.render_image_sha256 != render.image_sha256
                    or response.request_sha256 != render.request_sha256):
                raise ValueError("saved OCR response belongs to different render lineage")
            from novel_to_comic.page_ocr import _PageOCRDraft, build_extraction
            raw = RawOCRObservation(
                page_number=page.page_number, render_revision=render.revision,
                render_image_sha256=render.image_sha256, usage=response.usage,
                extraction=build_extraction(
                    _PageOCRDraft.model_validate_json(response.raw_response)
                    if response.raw_response is not None
                    else _PageOCRDraft.model_validate(response.response)
                ),
            )
            artifacts.write_raw_ocr(raw)
            analysis = _validate_observations(page=page, render=render, raw=raw, artifacts=artifacts)
            record_analysis_issues(artifacts, analysis)
            return analysis
        # Previous validators retained blind observations, but their flat balloon
        # sorting does not become proven panel evidence on migration.
        raw = RawOCRObservation(
            page_number=page.page_number, render_revision=render.revision,
            render_image_sha256=render.image_sha256, usage=saved.analysis_usage,
            extraction=OCRExtraction(
                lettering=saved.ocr_observations, incidental_text=saved.incidental_text,
                observed_regions=saved.observed_regions,
                observed_reading_order=saved.observed_reading_order,
                reading_order_proven=saved.reading_order_proven,
            ),
        )
        artifacts.write_raw_ocr(raw)
    analysis = _validate_observations(page=page, render=render, raw=raw, artifacts=artifacts)
    record_analysis_issues(artifacts, analysis)
    return analysis


def _validate_observations(
    *, page: ComicPage, render: PageRenderRevision,
    raw: RawOCRObservation, artifacts: TargetArtifacts,
) -> RenderAnalysis:
    if (raw.schema_version != 1 or raw.page_number != page.page_number
            or raw.render_revision != render.revision
            or raw.render_image_sha256 != render.image_sha256):
        raise ValueError("saved OCR observations belong to different render bytes")
    extraction = raw.extraction
    from novel_to_comic.lettering.service import is_hybrid
    if is_hybrid(artifacts):
        matches, failures = (), ()
        issues = tuple(
            EditorialIssue(
                id=f"draw-page-{page.page_number:03d}-render-{render.revision:03d}-unexpected-{item.id}",
                owner_stage="draw", code="unexpected_generated_lettering",
                message="The base artwork contains possible generated comic lettering where quiet space was requested.",
                artifact_ids=(item.detected_region_id,) if item.detected_region_id else (),
                evidence=(f"Blind base-art observation: {item.text}",),
            )
            for item in extraction.lettering if item.role == "comic_lettering"
        )
    else:
        matches, failures, issues = _compare_lettering(page, render, extraction)
    analysis = RenderAnalysis(
        page_number=page.page_number,
        render_revision=render.revision,
        render_image_sha256=render.image_sha256,
        validator_version=DRAW_VALIDATOR_VERSION,
        comic_page_sha256=render.comic_page_sha256,
        reading_order_proven=extraction.reading_order_proven,
        punctuation_policy=PUNCTUATION_POLICY,
        recognized_lettering={
            match.lettering_item_id: match.observed_text for match in matches
        },
        ocr_observations=extraction.lettering,
        incidental_text=extraction.incidental_text,
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
        analysis_usage=raw.usage,
    )
    artifacts.write_analysis(analysis)
    return analysis


def record_analysis_issues(
    artifacts: TargetArtifacts,
    analysis: RenderAnalysis,
    *,
    lettering_item_ids: tuple[str, ...] = (),
) -> tuple[PageIssue, ...]:
    """Record optional transcription suggestions without blocking Book."""

    recorded: list[PageIssue] = []
    current_ids = {
        f"page-issue-{result.id}"
        for result in (*analysis.invariant_failures, *analysis.editorial_issues)
    }
    prefix = f"page-issue-draw-page-{analysis.page_number:03d}-render-{analysis.render_revision:03d}-"
    try:
        prior = artifacts.read_issues(analysis.page_number)
    except ArtifactMissing:
        prior = ()
    retained = tuple(
        issue for issue in prior
        if not (issue.id.startswith(prefix) and issue.id not in current_ids)
    )
    if retained != prior:
        artifacts.write_issues(analysis.page_number, retained)
    for result in (*analysis.invariant_failures, *analysis.editorial_issues):
        issue = PageIssue(
            id=f"page-issue-{result.id}",
            issue_type=result.code,
            classification="editorial_issue",
            correction_kind="render_fidelity",
            correction_owner="draw",
            page_number=analysis.page_number,
            render_revision=analysis.render_revision,
            evidence=result.evidence,
            requested_correction=(
                "Inspect this detected region on the base art. It may contain unwanted generated lettering; "
                "dismiss a false positive or correct the artwork explicitly. Software lettering edits do not remove raster text."
                if result.code == "unexpected_generated_lettering" else
                "Review the page order visually if desired; no redraw is required."
                if result.code == "unverified_lettering_order"
                else "Possible text difference. Compare the saved artwork with the script; "
                "the checker may have misread it. Redraw only if the artwork needs a correction."
            ),
            lettering_item_ids=() if result.code == "unexpected_generated_lettering" else (lettering_item_ids or result.artifact_ids),
            detected_region_ids=result.artifact_ids if result.code == "unexpected_generated_lettering" else (),
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
            issue.id for issue in issues if issue.status in {"open", "revised"}
        ),
        blocking_issue_ids=tuple(
            issue.id
            for issue in issues
            if issue.status in {"open", "revised"}
            and issue.classification == "invariant_failure"
            and issue.requires_resolution
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

    if issue.status not in {"open", "revised"}:
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
        issue_ids=(issue.id,),
        page_number=page.page_number,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        parent_render_revision=parent.revision,
        parent_render_image_sha256=parent.image_sha256,
        mode=intent.mode,
        instruction=intent.instruction,
        detected_region_ids=intent.detected_region_ids,
    )

def build_correction_context(
    *,
    page: ComicPage,
    artifacts: TargetArtifacts,
    extra_source_unit_ids: tuple[str, ...] = (),
) -> PageCorrectionContext:
    """Compile grounded bookwide context for one page correction.

    Every adapted beat summary travels with the request so the redraw stays
    consistent with the whole novel, while full source prose is limited to the
    units this page adapts plus the remote passages the author explicitly
    selected. Author-selected passages always arrive in full; only the
    automatically gathered page units are subject to the context budget.
    Provenance (adaptation revision/sha, beat and unit IDs, content digest)
    is persisted on the correction itself.
    """
    from novel_to_comic.target_artifacts import ArtifactMissing as _Missing

    try:
        adaptation = artifacts.read_adaptation()
    except _Missing as exc:
        raise InvalidCorrectionError("book adaptation is unavailable for correction context") from exc
    try:
        source = artifacts.read_source()
    except _Missing as exc:
        raise InvalidCorrectionError("source text is unavailable for correction context") from exc
    if len(extra_source_unit_ids) != len(set(extra_source_unit_ids)):
        raise InvalidCorrectionError("selected source passages must be unique")
    if len(extra_source_unit_ids) > MAX_CORRECTION_CONTEXT_SELECTED_UNITS:
        raise InvalidCorrectionError(
            f"correction selects {len(extra_source_unit_ids)} source passages; "
            f"at most {MAX_CORRECTION_CONTEXT_SELECTED_UNITS} per request"
        )
    page_beat_ids = tuple(dict.fromkeys(beat for content in page.content for beat in content.beat_ids))
    beats_by_id = {beat.id: beat for beat in adaptation.beats}
    units_by_id = {unit.id: unit for unit in source.units}
    unknown = [unit_id for unit_id in extra_source_unit_ids if unit_id not in units_by_id]
    if unknown:
        raise InvalidCorrectionError(
            "correction selects unknown source passages: " + ", ".join(sorted(unknown))
        )
    wanted_unit_ids: list[str] = []
    for beat_id in page_beat_ids:
        beat = beats_by_id.get(beat_id)
        if beat is None:
            continue
        for unit_id in (
            *beat.source_unit_ids,
            *(source_id for item in beat.lettering for source_id in item.source_unit_ids),
        ):
            if unit_id not in wanted_unit_ids:
                wanted_unit_ids.append(unit_id)
    for content in page.content:
        for lettering in content.lettering:
            for unit_id in lettering.source_unit_ids:
                if unit_id not in wanted_unit_ids:
                    wanted_unit_ids.append(unit_id)
    ordered_unit_ids = [unit.id for unit in sorted(
        (units_by_id[unit_id] for unit_id in wanted_unit_ids if unit_id in units_by_id),
        key=lambda unit: unit.ordinal,
    )]
    # Author-selected passages always arrive in full; the automatic page units
    # fill whatever budget remains. User-requested content is never truncated.
    source_texts: list[str] = []
    kept_unit_ids: list[str] = []
    for unit_id in extra_source_unit_ids:
        source_texts.append(units_by_id[unit_id].text)
        kept_unit_ids.append(unit_id)
    budget = MAX_CORRECTION_CONTEXT_SOURCE_CHARACTERS - sum(len(text) for text in source_texts)
    truncated = False
    for unit_id in ordered_unit_ids:
        if unit_id in kept_unit_ids:
            continue
        text = units_by_id[unit_id].text
        if len(text) > budget and kept_unit_ids:
            truncated = True
            break
        kept_text = text[:budget] if not kept_unit_ids and len(text) > budget else text
        source_texts.append(kept_text)
        kept_unit_ids.append(unit_id)
        budget -= len(kept_text)
        if budget <= 0:
            break
    kept_set = set(kept_unit_ids)
    omitted_unit_ids = tuple(unit_id for unit_id in ordered_unit_ids if unit_id not in kept_set)
    if omitted_unit_ids:
        truncated = True
    beat_ids = tuple(beat.id for beat in adaptation.beats)
    summaries = tuple(f"[{beat.order}] {beat.summary}" for beat in adaptation.beats)
    # Bookwide treatment spine: the causal backbone every redraw must respect.
    treatment_spine = tuple(adaptation.treatment.causal_spine) + tuple(
        f"Essential: {event}" for event in adaptation.treatment.essential_events
    )
    # Appearance chronology in beat order: who changed into what, and when.
    appearance_chronology = tuple(
        f"Beat {beat.id} [{beat.order}]: {change.entity_id} "
        f"{change.from_state_id or 'base'} -> {change.to_state_id}: {change.description}"
        for beat in adaptation.beats
        for change in beat.appearance_changes
    )
    # Remote continuity facts (time/place/knowledge/emotion) in beat order.
    beat_transitions = tuple(
        f"Beat {beat.id} [{beat.order}]: {transition.dimension} "
        f"{transition.scope_id}: {transition.from_state} -> {transition.to_state}: {transition.description}"
        for beat in adaptation.beats
        for transition in beat.transitions
    )
    digest = hashlib.sha256(
        json.dumps(
            {
                "adaptation_revision": adaptation.revision,
                "adaptation_sha256": adaptation.content_sha256,
                "beats": list(beat_ids),
                "summaries": list(summaries),
                "treatment": list(treatment_spine),
                "appearances": list(appearance_chronology),
                "sources": kept_unit_ids,
                "texts": source_texts,
                "selected": list(extra_source_unit_ids),
                "omitted": list(omitted_unit_ids),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return PageCorrectionContext(
        beat_ids=beat_ids,
        beat_summaries=summaries,
        treatment_spine=treatment_spine,
        appearance_chronology=appearance_chronology,
        beat_transitions=beat_transitions,
        source_unit_ids=tuple(kept_unit_ids),
        source_texts=tuple(source_texts),
        omitted_source_unit_ids=omitted_unit_ids,
        selected_source_unit_ids=tuple(extra_source_unit_ids),
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        digest=digest,
        truncated=truncated,
    )


def deterministic_manual_issue_id(*, page_number: int, parent_revision: int, change_id: str) -> str:
    """The stable issue identity for one manual change, computed without writes.

    Preview and submission derive the same IDs, so both compile the identical
    frozen request. The issue itself is created later, inside the reserved job.
    """
    return f"page-issue-manual-{page_number}-{parent_revision}-{change_id}"


def ensure_correction_issues(
    artifacts: TargetArtifacts,
    *,
    correction: PageRenderCorrection,
) -> tuple[PageIssue, ...]:
    """Create missing manual issues inside the reserved job lifecycle.

    Called at the top of the correction job, after credit reservation, so a
    rejected preview or a lost submit race never leaves orphan issues behind.
    Creation is idempotent: a submit retry reuses the deterministic issue.
    """
    try:
        stored = artifacts.read_issues(correction.page_number)
    except ArtifactMissing:
        stored = ()
    by_id = {issue.id: issue for issue in stored}
    ensured: list[PageIssue] = []
    for change in correction.changes:
        if change.issue_id is None:
            raise ValueError(f"change {change.id!r} carries no issue identity")
        existing = by_id.get(change.issue_id)
        if existing is not None:
            ensured.append(existing)
            continue
        expected = deterministic_manual_issue_id(
            page_number=correction.page_number,
            parent_revision=correction.parent_render_revision,
            change_id=change.id,
        )
        if change.issue_id != expected:
            raise ValueError(f"linked page issue {change.issue_id!r} is missing")
        created = PageIssue(
            id=expected,
            issue_type="manual_change",
            classification="editorial_issue",
            correction_kind="render_fidelity",
            correction_owner="draw",
            page_number=correction.page_number,
            render_revision=correction.parent_render_revision,
            evidence=(
                change.instruction,
                *(annotation.note for annotation in change.annotations),
            ),
            requested_correction=change.instruction,
            status="open",
        )
        try:
            ensured.append(record_page_issue(artifacts, created))
        except ValueError:
            # A concurrent job won the race; reuse the winner.
            reread = {issue.id: issue for issue in artifacts.read_issues(correction.page_number)}
            ensured.append(reread[change.issue_id])
        by_id[change.issue_id] = ensured[-1]
    return tuple(ensured)


def _check_effective_issue_lineage(issue: PageIssue, parent: PageRenderRevision) -> None:
    """Accept the lineage a revised issue actually carries.

    A revised issue retains its original render_revision and gains the
    resolution_revision that addressed it. Re-fixing it targets the current
    render only when that resolution revision is current; otherwise the
    request is stale. Open issues must cite the current render directly.
    """
    if issue.status == "revised":
        if issue.resolution_revision != parent.revision:
            raise StaleCorrectionError(
                f"page issue {issue.id!r} was revised by render {issue.resolution_revision}, "
                f"not current render {parent.revision}"
            )
    elif issue.render_revision != parent.revision:
        raise StaleCorrectionError(
            f"page issue {issue.id!r} targets render {issue.render_revision}, "
            f"not current render {parent.revision}"
        )


def build_aggregated_correction_request(
    *,
    changes: tuple[CorrectionChange, ...],
    note: str = "",
    context_source_unit_ids: tuple[str, ...] = (),
    page: ComicPage,
    parent: PageRenderRevision,
    profile: PageCapabilityProfile,
    artifacts: TargetArtifacts,
) -> PageRenderCorrection:
    """Aggregate one explicit editable correction set into a full-page request.

    Each change either edits the directive of a linked tracked issue or carries
    a manual instruction. Manual changes receive their deterministic issue
    identity here, purely computed, so preview and submission compile the
    identical frozen request; the real PageIssue is created later, inside the
    reserved job. Unselected issues remain untouched. Manual text is accepted
    verbatim: no keyword classification is attempted, so a note asking to
    change canonical wording cannot be detected here. That case stays safe
    because compilation pins exact lettering and the preview warns that
    wording changes need the story workflow instead.
    """
    cleaned_note = note.strip()
    if len(changes) != len({change.id for change in changes}):
        raise InvalidCorrectionError("correction change IDs must be unique")
    if len(changes) > MAX_CORRECTION_CHANGES:
        raise InvalidCorrectionError(
            f"correction has {len(changes)} changes; at most {MAX_CORRECTION_CHANGES} per request"
        )
    linked_ids = [change.issue_id for change in changes if change.issue_id is not None]
    if len(linked_ids) != len(set(linked_ids)):
        raise InvalidCorrectionError("correction changes must link distinct issues")
    for change in changes:
        if not change.instruction.strip():
            raise InvalidCorrectionError(f"change {change.id!r} instruction must not be blank")
        if len(change.instruction) > MAX_CORRECTION_NOTE_CHARACTERS:
            raise InvalidCorrectionError(f"change {change.id!r} instruction exceeds 1000 characters")
    if len(cleaned_note) > MAX_CORRECTION_NOTE_CHARACTERS:
        raise InvalidCorrectionError("correction note exceeds 1000 characters")
    total_annotations = sum(len(change.annotations) for change in changes)
    if total_annotations > MAX_CORRECTION_ANNOTATIONS:
        raise InvalidCorrectionError(
            f"correction has {total_annotations} annotations; at most {MAX_CORRECTION_ANNOTATIONS} per request"
        )
    if not changes and not cleaned_note:
        raise InvalidCorrectionError("correction requires changes or an author note")
    if parent.page_number != page.page_number:
        raise StaleCorrectionError("correction parent belongs to a different page")
    if parent.is_stale_for(page):
        raise StaleCorrectionError("correction parent is stale for the canonical ComicPage")
    try:
        parent_bytes = artifacts.read_render(parent.page_number, parent.revision)
    except ArtifactMissing as exc:
        raise StaleCorrectionError("correction parent render bytes are unavailable") from exc
    if hashlib.sha256(parent_bytes).hexdigest() != parent.image_sha256:
        raise StaleCorrectionError("correction parent bytes do not match render lineage")
    try:
        stored = artifacts.read_issues(page.page_number)
    except ArtifactMissing:
        stored = ()
    by_id = {issue.id: issue for issue in stored}
    selected: list[PageIssue] = []
    records: list[CorrectionChange] = []
    for change in changes:
        if change.issue_id is not None:
            issue = by_id.get(change.issue_id)
            if issue is None:
                raise InvalidCorrectionError(f"page issue {change.issue_id!r} was not found")
            if issue.page_number != page.page_number:
                raise InvalidCorrectionError(f"page issue {change.issue_id!r} belongs to a different page")
            if issue.status not in {"open", "revised"}:
                raise InvalidCorrectionError(f"page issue {change.issue_id!r} is already {issue.status}")
            if issue.correction_owner != "draw" or issue.correction_kind != "render_fidelity":
                raise InvalidCorrectionError(
                    f"page issue {change.issue_id!r} changes canonical copy and requires a story change, not image correction"
                )
            _check_effective_issue_lineage(issue, parent)
            selected.append(issue)
            records.append(change.model_copy(update={"issue_id": issue.id}))
        else:
            manual_id = deterministic_manual_issue_id(
                page_number=page.page_number, parent_revision=parent.revision, change_id=change.id,
            )
            if manual_id in by_id:
                raise InvalidCorrectionError(
                    f"change {change.id!r} was already submitted; reuse its tracked issue instead"
                )
            records.append(change.model_copy(update={"issue_id": manual_id}))
    region_ids = tuple(dict.fromkeys(
        region_id for issue in selected for region_id in issue.detected_region_ids
    ))
    mode = "region_targeted" if region_ids else "instructed"
    resolved_regions = ()
    if region_ids:
        try:
            analysis = artifacts.read_analysis(parent.page_number, parent.revision)
        except ArtifactMissing as exc:
            raise InvalidCorrectionError("detected regions are unavailable for this render") from exc
        if analysis.render_image_sha256 != parent.image_sha256:
            raise InvalidCorrectionError("detected regions belong to different render bytes")
        resolved_regions = tuple(
            region for region in analysis.observed_regions if region.id in region_ids
        )
        known_regions = {region.id for region in analysis.observed_regions}
        unknown = [region_id for region_id in region_ids if region_id not in known_regions]
        if unknown:
            raise InvalidCorrectionError(
                "page issue cites an unknown detected region: " + ", ".join(sorted(unknown))
            )
    if mode not in profile.editing_modes:
        label = "region-targeted" if mode == "region_targeted" else "instructed"
        raise InvalidCorrectionError(f"selected profile does not support {label} correction")
    context = build_correction_context(
        page=page, artifacts=artifacts, extra_source_unit_ids=tuple(context_source_unit_ids),
    )
    directives = ["Correct these findings in one complete page revision:"]
    for record in records:
        directives.append(
            f"- [change {record.id} tracks {record.issue_id}] {record.instruction.strip()}"
        )
    if cleaned_note:
        directives.append("Author note (image-only; canonical lettering stays exact):")
        directives.append(f"- {cleaned_note}")
    ordered_annotations = [annotation for record in records for annotation in record.annotations]
    if ordered_annotations:
        directives.append("Annotations (normalized page fractions, origin top-left):")
        directives.extend(
            annotation.provider_guidance(index)
            for index, annotation in enumerate(ordered_annotations, 1)
        )
    producing = next((
        request for revision in reversed(artifacts.request_revisions(parent.page_number))
        if (request := artifacts.read_request(parent.page_number, revision)).request_sha256
        == parent.request_sha256
    ), None)
    if producing is None:
        raise InvalidCorrectionError("correction parent lacks its producing request")
    previous = producing.correction
    retained = previous.retained_instructions if previous else (producing.prompt,)
    if previous:
        retained += tuple(change.instruction for change in previous.changes)
        retained += tuple(
            annotation.provider_guidance(index)
            for change in previous.changes
            for index, annotation in enumerate(change.annotations, 1)
        )
        if previous.note:
            retained += (previous.note,)
        if not previous.changes and not previous.note:
            retained += (previous.instruction,)
    return PageRenderCorrection(
        issue_ids=tuple(record.issue_id for record in records if record.issue_id is not None),
        page_number=page.page_number,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        parent_render_revision=parent.revision,
        parent_render_image_sha256=parent.image_sha256,
        mode=mode,
        instruction="\n".join(directives),
        detected_region_ids=region_ids,
        resolved_regions=resolved_regions,
        depiction=previous.depiction if previous else "canonical",
        retained_instructions=tuple(dict.fromkeys(retained)),
        changes=tuple(records),
        note=cleaned_note,
        context_beat_ids=context.beat_ids,
        context_source_unit_ids=context.source_unit_ids,
        context_selected_source_unit_ids=context.selected_source_unit_ids,
        context_adaptation_revision=context.adaptation_revision,
        context_adaptation_sha256=context.adaptation_sha256,
        context_digest=context.digest,
        context_truncated=context.truncated,
    )


def resolve_page_issue(
    artifacts: TargetArtifacts,
    *,
    issue_id: str,
    page_number: int,
    resolution_revision: int,
    verified: bool = True,
) -> PageIssue:
    """Link an issue to the complete page revision produced for it."""

    issues = artifacts.read_issues(page_number)
    resolved: PageIssue | None = None
    updated: list[PageIssue] = []
    for issue in issues:
        if issue.id == issue_id:
            if (
                issue.status == ("resolved" if verified else "revised")
                and issue.resolution_revision == resolution_revision
            ):
                return issue
            if issue.status not in {"open", "revised"}:
                raise ValueError("only an open page issue can be resolved")
            resolved = issue.model_copy(
                update={
                    "status": "resolved" if verified else "revised",
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
            if issue.status not in {"open", "revised"}:
                raise ValueError("only an open page issue can be accepted")
            if issue.classification == "invariant_failure":
                raise ValueError("an invariant failure cannot be deliberately accepted")
            accepted = PageIssue.model_validate(
                issue.model_copy(update={"status": "resolved" if issue.status == "revised" else "accepted"}).model_dump()
            )
            updated.append(accepted)
        else:
            updated.append(issue)
    if accepted is None:
        raise ValueError(f"page issue {issue_id!r} was not found")
    artifacts.write_issues(page_number, tuple(updated))
    return accepted


def dismiss_page_issue(
    artifacts: TargetArtifacts,
    *,
    issue_id: str,
    page_number: int,
    reason: str,
) -> PageIssue:
    """Dismiss an automated Draw finding that visual review disproved.

    This is not acceptance of a known invariant failure. It records that the
    detector's evidence was a false positive, preserving the audit trail while
    removing a finding that is no longer considered proven.
    """

    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("a dismissal reason is required")
    issues = artifacts.read_issues(page_number)
    dismissed: PageIssue | None = None
    updated: list[PageIssue] = []
    for issue in issues:
        if issue.id == issue_id:
            if issue.status not in {"open", "revised"}:
                raise ValueError("only an open page issue can be dismissed")
            if not issue.id.startswith("page-issue-draw-page-"):
                raise ValueError("only an automated Draw finding can be dismissed")
            dismissed = PageIssue.model_validate(
                issue.model_copy(
                    update={
                        "status": "dismissed",
                        "resolution_revision": None,
                        "dismissal_reason": clean_reason,
                    }
                ).model_dump()
            )
            updated.append(dismissed)
        else:
            updated.append(issue)
    if dismissed is None:
        raise ValueError(f"page issue {issue_id!r} was not found")
    artifacts.write_issues(page_number, tuple(updated))
    return dismissed
