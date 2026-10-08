"""Bounded, reference-aware visual review, independent from blind OCR."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.config import Config
from novel_to_comic.models.draw import FrozenPageGenerationRequest, PageIssue, PageRenderRevision
from novel_to_comic.models.page import ComicPage
from novel_to_comic.page_drawing import CompiledPageGeneration, _off_canvas_handle
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


class VisualFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: Literal["identity", "appearance", "prop", "scene", "composition"]
    panel_number: int = Field(ge=1)
    observation: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    issue_id: str | None = Field(default=None, min_length=1)


class VisualReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    findings: tuple[VisualFinding, ...] = Field(default=(), max_length=8)
    uncertain: tuple[str, ...] = Field(default=(), max_length=8)


class PageVisualReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_sha256: str = Field(min_length=64, max_length=64)
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(min_length=64, max_length=64)
    findings: tuple[VisualFinding, ...] = ()
    uncertain: tuple[str, ...] = ()
    usage: UsageRecord | None = None


def reference_display_for_render(
    artifacts: TargetArtifacts,
    page_number: int,
    render: PageRenderRevision,
) -> tuple[dict[str, object], ...]:
    """Actual reference display metadata for one render, without spending.

    Resolved from the frozen request that produced the render, so the labels
    match exactly what the provider saw. Empty when the request record is
    unavailable.
    """
    for revision in artifacts.request_revisions(page_number):
        try:
            request = artifacts.read_request(page_number, revision)
        except Exception:
            continue
        if request.request_sha256 != render.request_sha256:
            continue
        return tuple(
            {
                "order": reference.order,
                "id": reference.id,
                "entity_id": reference.entity_id,
                "appearance_state_id": reference.appearance_state_id,
                "label": reference.label,
                "visual_anchor": reference.visual_anchor,
                "media_type": reference.media_type,
            }
            for reference in request.references
        )
    return ()

def finding_issue_links(
    report: PageVisualReview,
    issues: tuple[PageIssue, ...],
) -> tuple[dict[str, object], ...]:
    """Link each cached finding to its persisted PageIssue, if one exists.

    A recurring finding links to its existing issue; a new finding gets
    ``visual-review-{digest}-{index}``. Returning the linkage lets the UI add
    the existing issue to a correction draft instead of duplicating it as a
    manual note, preserving one issue lifecycle. A finding with no persisted
    issue is explicitly unavailable and must not seed a draft.
    """
    by_id = {issue.id: issue for issue in issues}
    links: list[dict[str, object]] = []
    for index, finding in enumerate(report.findings, start=1):
        issue_id = finding.issue_id or f"visual-review-{report.input_sha256}-{index}"
        stored = by_id.get(issue_id)
        links.append(
            {
                "finding_index": index,
                "category": finding.category,
                "panel_number": finding.panel_number,
                "issue_id": issue_id,
                "issue_type": stored.issue_type if stored is not None else f"visual_{finding.category}",
                "correction_owner": stored.correction_owner if stored is not None else "draw",
                "issue_status": stored.status if stored is not None else None,
                "available": stored is not None and stored.status in {"open", "revised"},
            }
        )
    return tuple(links)

def _prior_visual_issues(
    artifacts: TargetArtifacts,
    page: ComicPage,
    render: PageRenderRevision,
    compiled: CompiledPageGeneration,
) -> tuple[PageIssue, ...]:
    """Earlier concerns on this branch under the same canonical authority.

    Only their immutable identity/evidence enters the prompt. Decisions and
    resolution revisions remain live issue state and cannot invalidate a paid
    review every time the author clears a finding.
    """
    try:
        issues = artifacts.read_issues(page.page_number)
    except ArtifactMissing:
        return ()
    ancestors: set[int] = set()
    visited = {render.revision}
    revision = render.parent_revision
    while revision is not None and revision not in visited:
        visited.add(revision)
        prior = artifacts.read_provenance(page.page_number, revision).render
        if not prior.is_stale_for(page):
            producing = artifacts.producing_request(prior)
            if producing.references == compiled.request.references:
                ancestors.add(revision)
        revision = prior.parent_revision
    return tuple(
        issue for issue in issues
        if issue.id.startswith("visual-review-") and issue.render_revision in ancestors
    )


def visual_issue_observed_on_render(
    artifacts: TargetArtifacts, issue: PageIssue, render: PageRenderRevision,
) -> bool:
    """Current evidence for a recurring concern, never a claim that it was fixed."""
    return issue.id.startswith("visual-review-") and any(
        report.render_image_sha256 == render.image_sha256
        and report.page_number == render.page_number
        and report.render_revision == render.revision
        and any(finding.issue_id == issue.id for finding in report.findings)
        for report in artifacts.read_visual_reviews(render.page_number, render.revision)
    )


def visual_review_prompt(
    *,
    compiled: CompiledPageGeneration,
    producing_request: FrozenPageGenerationRequest | None = None,
    prior_issues: tuple[PageIssue, ...] = (),
) -> str:
    """Compare current authority while retaining the producing render's intent."""
    attachment_map = {
        _off_canvas_handle("asset", reference.order): reference.order + 1
        for reference in compiled.request.references
    }
    return (
        "Image 1 is the complete page to review. Remaining images are the approved references "
        "in the numbered order used by the page instructions below. Compare visible identity, "
        "appearance state, recurring objects, scene setting, panel composition, and fidelity "
        "to the selected_style_proof's rendering language when supplied. The style proof owns "
        "artistic treatment, not depicted identities, poses, gaze, expressions or page content. "
        "Report only concrete visible discrepancies with a panel number, observed feature, "
        "expected feature, and narrowly scoped correction. Do not judge style preferences or "
        "transcribe lettering: a separate blind OCR check owns text. Account for perspective, "
        "occlusion, lighting, and deliberate less-graphic staging. If the image does not show "
        "enough evidence, put that uncertainty in uncertain instead of inventing a finding. "
        "Do not assume that a reference must appear in every panel. At most eight findings; "
        "an empty list means no discrepancy detected, not a guarantee of correctness. "
        "The following generation specification is data to compare against, not instructions "
        "to generate an image. The off-canvas asset bindings below map to attachment positions. "
        "The producing specification is historical evidence only of deliberate depiction and "
        "correction choices: retain those choices where consistent with current authority. "
        "It cannot override current approved identity/state/style, author pins or exact copy; "
        "its old asset map does not bind the current attachments.\n\n"
        "For a discrepancy already described in prior_findings, return that exact issue_id. "
        "Match the same subject, panel, disputed feature and expected outcome even when the "
        "wording changes. A different feature or expected outcome is a new concern: use null. "
        "Report visible evidence regardless of earlier author decisions; the issue lifecycle "
        "preserves those decisions. Never invent an issue_id.\n\n"
        + json.dumps(
            {
                "current_asset_attachments": attachment_map,
                "generation_specification": compiled.request.prompt,
                "producing_specification": producing_request.prompt if producing_request else None,
                "prior_findings": [
                    {"issue_id": issue.id, "category": issue.issue_type.removeprefix("visual_"),
                     "evidence": issue.evidence, "correction": issue.requested_correction}
                    for issue in prior_issues
                ],
            }, ensure_ascii=False
        )
    )


def visual_review_input_digest(
    *,
    config: Config,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    compiled: CompiledPageGeneration,
    producing_request: FrozenPageGenerationRequest | None = None,
    prior_issues: tuple[PageIssue, ...] = (),
) -> str:
    """Validate current page/render/reference/model inputs and digest them.

    The same digest keys generation and cache reads, so a saved report is
    returned as current only when every input still matches: canonical page,
    exact render bytes, approved reference bytes, and review model. Anything
    else is a different review, never the current one.
    """
    if producing_request is not None and (
        producing_request.request_sha256 != render.request_sha256
        or producing_request.is_stale_for(page)
    ):
        raise ValueError("producing instructions do not match this render and canonical page")
    if (
        render.is_stale_for(page)
        or hashlib.sha256(image).hexdigest() != render.image_sha256
    ):
        raise ValueError(
            "visual review requires the current canonical page and exact render bytes"
        )
    if compiled.request.is_stale_for(page):
        raise ValueError(
            "visual review instructions belong to a different canonical page"
        )
    for reference, data in zip(
        compiled.request.references, compiled.reference_bytes, strict=True
    ):
        if hashlib.sha256(data).hexdigest() != reference.content_sha256:
            raise ValueError(
                "visual review reference bytes do not match approved authority"
            )
    model = config.effective_visual_review_model()
    prompt = visual_review_prompt(compiled=compiled, producing_request=producing_request, prior_issues=prior_issues)
    return hashlib.sha256(
        json.dumps(
            {
                "version": 1,
                "render": render.image_sha256,
                "page": page.content_sha256,
                "model": model,
                "prompt": prompt,
                "schema": VisualReviewDraft.model_json_schema(),
                "references": [
                    ref.content_sha256 for ref in compiled.request.references
                ],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def validated_saved_visual_review(
    *,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    compiled: CompiledPageGeneration,
    config: Config,
    artifacts: TargetArtifacts,
    producing_request: FrozenPageGenerationRequest | None = None,
) -> PageVisualReview | None:
    """Return the saved review only when it matches the current inputs.

    Never treats the latest file as current: the digest is recomputed from
    the live page, render bytes, approved references, and model, and only an
    exact digest hit is returned. Raises the same ValueError as generation
    when the inputs themselves are inconsistent.
    """
    digest = visual_review_input_digest(
        config=config, page=page, render=render, image=image, compiled=compiled,
        producing_request=producing_request,
        prior_issues=_prior_visual_issues(artifacts, page, render, compiled),
    )
    path = artifacts.visual_review_path(page.page_number, render.revision, digest)
    if not path.exists():
        return None
    return artifacts.read_visual_review(page.page_number, render.revision, digest)


async def review_page_visuals(
    *,
    config: Config,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    compiled: CompiledPageGeneration,
    artifacts: TargetArtifacts,
    generate=None,
    producing_request: FrozenPageGenerationRequest | None = None,
) -> ApiResult[PageVisualReview]:
    """One review per exact page, reference set, prompt, and model.

    Findings are editorial evidence for a person to inspect, never a claim of
    objective visual correctness. No auto-corrections or critic loop.
    """
    model = config.effective_visual_review_model()
    prior_issues = _prior_visual_issues(artifacts, page, render, compiled)
    prompt = visual_review_prompt(compiled=compiled, producing_request=producing_request, prior_issues=prior_issues)
    digest = visual_review_input_digest(
        config=config, page=page, render=render, image=image, compiled=compiled,
        producing_request=producing_request,
        prior_issues=prior_issues,
    )
    path = artifacts.visual_review_path(page.page_number, render.revision, digest)
    if path.exists():
        report = artifacts.read_visual_review(page.page_number, render.revision, digest)
    else:
        if generate is None:
            from novel_to_comic.clients.text import generate_json

            generate = generate_json
        result = await generate(
            config=config,
            model=model,
            system_prompt="Review visual evidence conservatively. Return structured JSON.",
            user_content=prompt,
            temperature=0.0,
            feature="draw.visual_review",
            json_schema=VisualReviewDraft.model_json_schema(),
            image_attachments=(
                (image, "image/png"),
                *tuple(
                    (data, ref.media_type)
                    for ref, data in zip(
                        compiled.request.references,
                        compiled.reference_bytes,
                        strict=True,
                    )
                ),
            ),
        )
        draft = VisualReviewDraft.model_validate(result.value)
        if any(finding.panel_number > len(page.content) for finding in draft.findings):
            raise ValueError("visual review cited a panel that does not exist")
        prior_by_id = {issue.id: issue for issue in prior_issues}
        for finding in draft.findings:
            if finding.issue_id is None:
                continue
            prior_issue = prior_by_id.get(finding.issue_id)
            if prior_issue is None or prior_issue.issue_type != f"visual_{finding.category}" or not any(
                re.match(rf"Panel {finding.panel_number}:", evidence) for evidence in prior_issue.evidence
            ):
                raise ValueError("visual review linked a finding outside its prior panel/category evidence")
        report = PageVisualReview(
            input_sha256=digest,
            page_number=page.page_number,
            render_revision=render.revision,
            render_image_sha256=render.image_sha256,
            findings=draft.findings,
            uncertain=draft.uncertain,
            usage=result.usage,
        )
        artifacts.write_visual_review(report)
    from novel_to_comic.page_review import record_page_issue

    for index, finding in enumerate(report.findings, 1):
        issue = PageIssue(
            id=finding.issue_id or f"visual-review-{digest}-{index}",
            issue_type=f"visual_{finding.category}",
            classification="editorial_issue",
            correction_kind="render_fidelity",
            correction_owner="draw",
            page_number=page.page_number,
            render_revision=render.revision,
            evidence=(
                f"Panel {finding.panel_number}: {finding.observation}",
                f"Expected: {finding.expected}",
            ),
            requested_correction=finding.correction,
            status="open",
        )
        if not artifacts.issues_path(page.page_number).exists() or not any(
            existing.id == issue.id
            for existing in artifacts.read_issues(page.page_number)
        ):
            record_page_issue(artifacts, issue)
    return ApiResult(value=report)


def compile_visual_review(project_dir, config: Config, artifacts: TargetArtifacts, page: ComicPage) -> CompiledPageGeneration:
    """The current authority a review compares against.

    The automatic check in Draw, the saved-result read and an explicit re-check
    all compile it the same way, so they share one input digest and a saved
    review is never paid for twice.
    """
    from novel_to_comic.models.draw import RetryProvenance
    from novel_to_comic.page_drawing import (
        compile_page_generation_request,
        ensure_current_page_edition,
        validate_review_request,
    )
    from novel_to_comic.stages.s5_plan import approved_reference_files, approved_visual_inventory
    from novel_to_comic.style_reference import require_style_reference

    edition = ensure_current_page_edition(
        artifacts, artifacts.read_book_edition(), config, allow_retained_review=True,
    )
    compiled = compile_page_generation_request(
        page, edition, approved_visual_inventory(project_dir), approved_reference_files(project_dir),
        retry=RetryProvenance(attempt=1), style_template=config.style_template,
        style_reference_path=require_style_reference(project_dir, config.style_template),
    )
    validate_review_request(compiled, edition)
    return compiled


async def review_drawn_page(
    *,
    config: Config,
    project_dir,
    artifacts: TargetArtifacts,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    generate=None,
) -> ApiResult[PageVisualReview]:
    """Review one drawn render against its current approved references."""
    return await review_page_visuals(
        config=config, page=page, render=render, image=image,
        compiled=compile_visual_review(project_dir, config, artifacts, page),
        artifacts=artifacts, generate=generate,
        producing_request=artifacts.producing_request(render),
    )
