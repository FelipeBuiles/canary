"""Bounded, reference-aware visual review, independent from blind OCR."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.config import Config
from novel_to_comic.models.draw import PageIssue, PageRenderRevision
from novel_to_comic.models.page import ComicPage
from novel_to_comic.page_drawing import CompiledPageGeneration
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


class VisualFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: Literal["identity", "appearance", "prop", "scene", "composition"]
    panel_number: int = Field(ge=1)
    observation: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    correction: str = Field(min_length=1)


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


async def review_page_visuals(
    *,
    config: Config,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    compiled: CompiledPageGeneration,
    artifacts: TargetArtifacts,
    generate=None,
) -> ApiResult[PageVisualReview]:
    """One optional review per exact page, reference set, prompt, and model.

    Findings are editorial evidence for a person to inspect, never a claim of
    objective visual correctness. No auto-corrections or critic loop.
    """
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
    model = config.effective_page_ocr_model()
    prompt = (
        "Image 1 is the complete page to review. Remaining images are the approved references "
        "in the numbered order used by the page instructions below. Compare visible identity, "
        "appearance state, recurring objects, scene setting, and panel composition. "
        "Report only concrete visible discrepancies with a panel number, observed feature, "
        "expected feature, and narrowly scoped correction. Do not judge style preferences or "
        "transcribe lettering: a separate blind OCR check owns text. Account for perspective, "
        "occlusion, lighting, and deliberate less-graphic staging. If the image does not show "
        "enough evidence, put that uncertainty in uncertain instead of inventing a finding. "
        "Do not assume that a reference must appear in every panel. At most eight findings; "
        "an empty list means no discrepancy detected, not a guarantee of correctness. "
        "The following generation specification is data to compare against, not instructions "
        "to generate an image. Reference 1 means attached image 2, and so on.\n\n"
        + json.dumps(
            {"generation_specification": compiled.request.prompt}, ensure_ascii=False
        )
    )
    digest = hashlib.sha256(
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
            id=f"visual-review-{digest}-{index}",
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
