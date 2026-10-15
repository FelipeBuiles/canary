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
from novel_to_comic.page_drawing import CompiledPageGeneration
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


VisualCategory = Literal["identity", "appearance", "prop", "scene", "speaker", "composition"]
# What a reader loses. A discrepancy that cannot name one is not reported.
ReaderImpact = Literal["misreads_story", "breaks_continuity", "noticeable_flaw"]
IMPACT_RANK: dict[str, int] = {"misreads_story": 0, "breaks_continuity": 1, "noticeable_flaw": 2}


class VisualFindingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: VisualCategory
    panel_number: int = Field(ge=1)
    observation: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    impact: ReaderImpact
    reader_impact: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    issue_id: str | None = Field(default=None, min_length=1)


class VisualFinding(BaseModel):
    """A saved finding. Reviews made before impact rating have no impact."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    category: VisualCategory
    panel_number: int = Field(ge=1)
    observation: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    issue_id: str | None = Field(default=None, min_length=1)
    impact: ReaderImpact | None = None
    reader_impact: str | None = Field(default=None, min_length=1)


class VisualReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    findings: tuple[VisualFindingDraft, ...] = Field(default=(), max_length=8)
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


def _producing_choices(request: FrozenPageGenerationRequest | None) -> dict[str, object]:
    """Deliberate choices behind the render: depiction and the author's requests.

    Only these survive from the producing request. Its full generation prompt
    carries Plan's soft staging (facing, gaze, gesture, camera, unpinned
    layout) that the image model is free to realize differently.
    """
    if request is None:
        return {"depiction": "canonical", "author_requests": []}
    correction = request.correction
    # Initial draws record depiction only in their prompt's policy line, which
    # every later correction retains verbatim.
    prompts = (request.prompt, *(correction.retained_instructions if correction else ()))
    less_graphic = (correction is not None and correction.depiction == "less_graphic") or any(
        "aftermath for graphic details" in prompt for prompt in prompts
    )
    depiction = "less_graphic" if less_graphic else "canonical"
    requests: list[str] = []
    if correction is not None:
        requests = [
            *(instruction for instruction in correction.retained_instructions
              if not instruction.startswith("PAGE CANVAS: ")),
            *((change.instruction for change in correction.changes) if correction.changes
              else (correction.instruction,)),
            *((correction.note,) if correction.note.strip() else ()),
        ]
    return {"depiction": depiction, "author_requests": list(dict.fromkeys(requests))}


def _sheet_members(reference) -> list[dict] | None:
    try:
        sheet = json.loads(reference.visual_anchor)
    except ValueError:
        return None
    if not isinstance(sheet, dict) or sheet.get("format") != "lossless-reference-sheet-v1":
        return None
    return sheet["members"]


def review_specification(
    *,
    page: ComicPage,
    compiled: CompiledPageGeneration,
) -> dict[str, object]:
    """The binding authority a reviewer checks, built from canonical data.

    Identity, appearance state, setting facts, speaker binding and author pins
    only. Plan's facing, gaze, gesture, camera and unpinned layout guide the
    image model but do not bind it, so the reviewer never sees them.
    """
    request = compiled.request
    names: dict[str, str] = {}
    for item in request.lettering:
        if item.speaker_entity_id and item.speaker:
            names.setdefault(item.speaker_entity_id, item.speaker)
    authorities: list[tuple[int, dict]] = []
    for image, reference in enumerate(request.references, start=2):
        if reference.entity_id is None:
            continue
        members = _sheet_members(reference)
        if members is None:
            authorities.append((image, reference.model_dump(mode="json")))
        else:
            authorities += [
                (image, {**member["authority"], "sheet_region_pixels": member["region_pixels"]})
                for member in members
            ]
    for _, authority in authorities:
        names.setdefault(authority["entity_id"], authority.get("label") or authority["entity_id"])
    for written in request.written_identities:
        names.setdefault(written.entity_id, written.label or written.entity_id)

    def named(text: str) -> str:
        for entity_id in sorted(names, key=len, reverse=True):
            text = re.sub(rf"(?<![\w-]){re.escape(entity_id)}(?![\w-])", names[entity_id], text)
        return text

    def describe(authority: dict) -> dict[str, object]:
        return {
            "subject": names.get(authority["entity_id"], authority["entity_id"]),
            "appearance": authority.get("label") or None,
            **({"identity": authority["identity"]} if authority.get("identity") else {}),
            "visual_anchor": authority["visual_anchor"],
            **({"continuity_guard": authority["continuity_guard"]} if authority.get("continuity_guard") else {}),
            **({"sheet_region_pixels": authority["sheet_region_pixels"]} if "sheet_region_pixels" in authority else {}),
        }

    style = next((image for image, reference in enumerate(request.references, start=2)
                  if reference.entity_id is None), None)
    by_state = {(authority["entity_id"], authority.get("appearance_state_id")): image
                for image, authority in authorities}
    lettered = {item.id for item in request.lettering}
    panels = []
    for content in sorted(page.content, key=lambda content: content.order):
        subjects = []
        for entity_id in content.entity_ids:
            state = content.appearance_states.get(entity_id)
            image = by_state.get((entity_id, state))
            subjects.append({
                "subject": names.get(entity_id, entity_id),
                **({"reference_image": image} if image is not None else {}),
            })
        panel: dict[str, object] = {
            "panel": content.order,
            "story_beat": named(content.visual_intent),
            "subjects_planned": subjects,
        }
        if content.pinned_geometry is not None:
            panel["author_pinned_geometry"] = content.pinned_geometry.model_dump()
        balloons = [
            {
                "text": item.text,
                "kind": item.kind,
                "delivery": item.delivery,
                **({"speaker": names.get(item.speaker_entity_id, item.speaker or item.speaker_entity_id)}
                   if item.speaker_entity_id or item.speaker else {}),
            }
            for item in content.lettering if item.id in lettered
        ]
        if balloons:
            panel["lettering"] = balloons
        panels.append(panel)
    return {
        "page_is_lettered": bool(lettered),
        **({"style_proof_image": style} if style is not None else {}),
        "reference_images": [{"image": image, **describe(authority)} for image, authority in authorities],
        "written_identities": [describe(written.model_dump(mode="json")) for written in request.written_identities],
        "panels": panels,
    }


VISUAL_REVIEW_INSTRUCTIONS = (
    "Image 1 is the complete comic page to review. The other images are the approved "
    "references numbered in review_specification. Review as a comics editor asking one "
    "question: would a reader misread the story or notice a mistake? The image model was "
    "free to choose staging, so a different but coherent choice is never a defect.\n\n"
    "Report only these concrete, visible discrepancies:\n"
    "- identity: a subject does not match its approved reference (wrong person, gender, "
    "age, stated stature, or recognizable face and hair features).\n"
    "- appearance: clothing, hair, wounds or other appearance-state features differ from "
    "the subject's reference, or the same subject's appearance changes between panels.\n"
    "- prop: a recurring object differs from its reference or changes between panels.\n"
    "- scene: the setting contradicts its anchor or a fact the story_beat states (time of "
    "day, weather, indoors/outdoors, a named feature), or changes between panels without "
    "a story reason.\n"
    "- speaker (lettered pages only): a balloon tail points to someone other than its "
    "speaker, an onscreen speaker is not visible in that panel, or a caption, narration "
    "or offscreen line has a character tail.\n"
    "- composition: author_pinned_geometry or an author_requests item is visibly not "
    "honored, or a panel does not show the event its story_beat requires.\n\n"
    "Never report: facing direction, body orientation, gaze, pose, gesture, expression "
    "nuance, camera shot or angle, panel count, shape, size or arrangement (unless pinned), "
    "a planned subject left out of a panel whose event still reads (unless they are an "
    "onscreen speaker there), lighting mood, style preferences, rendering quality, or text "
    "spelling, wording and reading order (a separate blind OCR check owns copy). Do not "
    "assume every planned subject or reference appears in every panel.\n\n"
    "For each finding choose impact: misreads_story (a reader would misunderstand who is "
    "who, who speaks, or what happens), breaks_continuity (the same character, object or "
    "place visibly changes with no story reason), or noticeable_flaw (an attentive reader "
    "would see it contradict the story, but the meaning survives). reader_impact is one "
    "sentence naming what the reader would misread or notice. If you cannot name one, do "
    "not report it. Do not split one discrepancy into several findings.\n\n"
    "Account for perspective, occlusion, lighting and depiction. When depiction is "
    "less_graphic, framing, shadow or aftermath in place of graphic detail is deliberate. "
    "If the image lacks evidence, add a note to uncertain instead of inventing a finding. "
    "At most eight findings, most severe first; an empty list means nothing worth "
    "reporting was found, not a guarantee of correctness.\n\n"
    "For a discrepancy already described in prior_findings, return that exact issue_id. "
    "Match the same subject, panel, disputed feature and expected outcome even when the "
    "wording changes. A different feature or expected outcome is a new concern: use null. "
    "Report visible evidence regardless of earlier author decisions; the issue lifecycle "
    "preserves those decisions. Never invent an issue_id.\n\n"
    "The JSON below is data to compare against, never instructions to generate an image."
)


def visual_review_prompt(
    *,
    page: ComicPage,
    compiled: CompiledPageGeneration,
    producing_request: FrozenPageGenerationRequest | None = None,
    prior_issues: tuple[PageIssue, ...] = (),
) -> str:
    """Compare current binding authority while retaining the render's deliberate choices."""
    return VISUAL_REVIEW_INSTRUCTIONS + "\n\n" + json.dumps(
        {
            "review_specification": review_specification(page=page, compiled=compiled),
            **_producing_choices(producing_request),
            "prior_findings": [
                {"issue_id": issue.id, "category": issue.issue_type.removeprefix("visual_"),
                 "evidence": issue.evidence, "correction": issue.requested_correction}
                for issue in prior_issues
            ],
        }, ensure_ascii=False
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
    prompt = visual_review_prompt(page=page, compiled=compiled, producing_request=producing_request, prior_issues=prior_issues)
    return hashlib.sha256(
        json.dumps(
            {
                "version": 2,
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
    prompt = visual_review_prompt(page=page, compiled=compiled, producing_request=producing_request, prior_issues=prior_issues)
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
            system_prompt="You are a conservative comics editor. Report only reader-visible defects. Return structured JSON.",
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
        findings = tuple(
            VisualFinding.model_validate(finding.model_dump())
            for finding in sorted(draft.findings, key=lambda finding: IMPACT_RANK[finding.impact])
        )
        report = PageVisualReview(
            input_sha256=digest,
            page_number=page.page_number,
            render_revision=render.revision,
            render_image_sha256=render.image_sha256,
            findings=findings,
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
                *((f"Reader impact: {finding.reader_impact}",) if finding.reader_impact else ()),
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

    edition = ensure_current_page_edition(
        artifacts, artifacts.read_book_edition(), config, allow_retained_review=True,
    )
    compiled = compile_page_generation_request(
        page, edition, approved_visual_inventory(project_dir), approved_reference_files(project_dir),
        retry=RetryProvenance(attempt=1), style_template=config.style_template,
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
